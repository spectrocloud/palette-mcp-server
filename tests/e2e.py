# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0
#
# Test coverage tracking: tests/e2e_coverage.md
# Infrastructure helpers: tests/e2e_helpers.py

import os
import sys
from dataclasses import dataclass

from openai import OpenAI
from smolagents import OpenAIModel, ToolCallingAgent, ToolCollection

from e2e_helpers import (
    MCP_DOCKER_IMAGE,
    build_mcp_server_params,
    extract_tool_summary,
    extract_uid,
    fix_tool_schemas,
    get_hello_universe_pack_uid_from_terraform,
    make_step_callback,
    setup_kubectl,
    wait_for_cluster_running,
)

# ---------------------------------------------------------------------------
# Resource names — must match terraform resource definitions exactly.
# ---------------------------------------------------------------------------
CLUSTER_PROFILE_NAME = "add-on-profile"
DELETE_CLUSTER_PROFILE_NAME = "to-be-deleted"
HELLO_UNIVERSE_PACK_NAME = "hello-universe"
HELLO_UNIVERSE_PACK_DISPLAY_NAME = "Hello Universe"

CLUSTER_PROFILE_EXPECTED_TAGS = [
    "owner:ai-research-team",
    "terraform_managed:true",
    "env:test",
]
CLUSTER_EXPECTED_TAGS = [
    "owner:ai-research-team",
    "terraform_managed:true",
    "environment:test",
    "team:ai-research-team",
]

E2E_TEST_TAG = "e2e-test:true"

# ---------------------------------------------------------------------------
# Model and prompt configuration
# ---------------------------------------------------------------------------

E2E_MODEL = os.environ.get("E2E_MODEL", "gpt-4o")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "gpt-4o-mini")

# System prompt for the tester agent: constrains it to exactly one tool call per step.
AGENT_SYSTEM_PROMPT = (
    "You are an automated test runner for the Palette MCP server. "
    "For each task you are given exactly one thing to do: call the specified MCP tool "
    "with the specified arguments and report the result. "
    "Do not call extra tools, do not speculate, and do not retry unless the first call returned an error. "
    "Always follow the output format instructions in the prompt exactly."
)

# System prompt for the LLM judge: frames its role and scoring contract.
JUDGE_SYSTEM_PROMPT = (
    "You are a strict, impartial test judge for an automated end-to-end test suite. "
    "Your only job is to decide PASS or FAIL for a single test step based on the evidence provided. "
    "Do not infer intent, do not give partial credit, and do not make assumptions beyond what is shown. "
    "Respond with exactly the format requested — nothing else."
)

# ---------------------------------------------------------------------------
# Test case definitions
# ---------------------------------------------------------------------------


@dataclass
class E2ETestCase:
    name: str
    prompt: str
    required_tool: str
    required_action: str
    required_resource_type: str | None
    judge_goal: str


@dataclass
class E2ETestResult:
    name: str
    passed: bool
    tool_summary: str
    agent_output: str
    judge_verdict: str


def build_test_case_factories():
    """Return an ordered list of factory functions, each taking a state dict.

    Each factory is called immediately before its test case runs, so UIDs
    discovered by earlier steps are available when the prompt is built.

    State keys: profile_uid, cluster_uid, delete_profile_uid.
    """

    def _uid_or_unknown(state, key):
        return state.get(key) or "UNKNOWN (prior step did not produce a UID)"

    return [
        # Step 1 — list cluster profiles, discover profile UID
        lambda _s: E2ETestCase(
            name="list_cluster_profiles",
            prompt=(
                f'Call gather_or_delete_clusterprofiles with action="list". '
                f'Find the cluster profile named "{CLUSTER_PROFILE_NAME}" in the results '
                f"and confirm it is present. "
                f"End your response with exactly: PROFILE_UID: <uid>"
            ),
            required_tool="gather_or_delete_clusterprofiles",
            required_action="list",
            required_resource_type=None,
            judge_goal=f'"{CLUSTER_PROFILE_NAME}" is present in the list response and its UID is reported as PROFILE_UID.',
        ),
        # Step 2 — get cluster profile by UID
        lambda s: E2ETestCase(
            name="get_cluster_profile",
            prompt=(
                f'Call gather_or_delete_clusterprofiles with action="get" and '
                f'uid="{_uid_or_unknown(s, "profile_uid")}". '
                f'Confirm the profile name is "{CLUSTER_PROFILE_NAME}".'
            ),
            required_tool="gather_or_delete_clusterprofiles",
            required_action="get",
            required_resource_type=None,
            judge_goal=f'Profile name "{CLUSTER_PROFILE_NAME}" is confirmed in the get response.',
        ),
        # Step 3 — list clusters, confirm the known cluster UID is present and Running
        lambda s: E2ETestCase(
            name="list_clusters",
            prompt=(
                f'Call gather_or_delete_clusters with action="list" and active_only=True. '
                f'Find the cluster with UID "{_uid_or_unknown(s, "cluster_uid")}" in the results '
                f"and confirm it is in Running state. "
                f"End your response with exactly: CLUSTER_UID: {_uid_or_unknown(s, 'cluster_uid')}"
            ),
            required_tool="gather_or_delete_clusters",
            required_action="list",
            required_resource_type=None,
            judge_goal="The cluster with the expected UID is present in the list response and is in Running state.",
        ),
        # Step 4 — get cluster by UID
        lambda s: E2ETestCase(
            name="get_cluster",
            prompt=(
                f'Call gather_or_delete_clusters with action="get" and '
                f'uid="{_uid_or_unknown(s, "cluster_uid")}". '
                f"Confirm the cluster was retrieved successfully."
            ),
            required_tool="gather_or_delete_clusters",
            required_action="get",
            required_resource_type=None,
            judge_goal="Cluster was retrieved successfully by UID.",
        ),
        # Step 5 — get tags for cluster profile
        lambda s: E2ETestCase(
            name="get_cluster_profile_tags",
            prompt=(
                f'Call search_and_manage_resource_tags with action="get", '
                f'resource_type="clusterprofiles", and '
                f'uid="{_uid_or_unknown(s, "profile_uid")}". '
                f"Verify ALL of the following tags are present in the response: "
                f"{CLUSTER_PROFILE_EXPECTED_TAGS}."
            ),
            required_tool="search_and_manage_resource_tags",
            required_action="get",
            required_resource_type="clusterprofiles",
            judge_goal=f"All tags {CLUSTER_PROFILE_EXPECTED_TAGS} are present in the cluster profile tags response.",
        ),
        # Step 6 — get tags for cluster
        lambda s: E2ETestCase(
            name="get_cluster_tags",
            prompt=(
                f'Call search_and_manage_resource_tags with action="get", '
                f'resource_type="spectroclusters", and '
                f'uid="{_uid_or_unknown(s, "cluster_uid")}". '
                f"Verify ALL of the following tags are present in the response: "
                f"{CLUSTER_EXPECTED_TAGS}."
            ),
            required_tool="search_and_manage_resource_tags",
            required_action="get",
            required_resource_type="spectroclusters",
            judge_goal=f"All tags {CLUSTER_EXPECTED_TAGS} are present in the cluster tags response.",
        ),
        # Step 7 — add e2e tag to cluster profile
        lambda s: E2ETestCase(
            name="add_tag_to_cluster_profile",
            prompt=(
                f'Call search_and_manage_resource_tags with action="create", '
                f'resource_type="clusterprofiles", '
                f'uid="{_uid_or_unknown(s, "profile_uid")}", and '
                f'tags=["{E2E_TEST_TAG}"]. '
                f'Confirm the tag "{E2E_TEST_TAG}" was added successfully.'
            ),
            required_tool="search_and_manage_resource_tags",
            required_action="create",
            required_resource_type="clusterprofiles",
            judge_goal=f'"{E2E_TEST_TAG}" tag was added to the cluster profile without error.',
        ),
        # Step 8 — add e2e tag to cluster
        lambda s: E2ETestCase(
            name="add_tag_to_cluster",
            prompt=(
                f'Call search_and_manage_resource_tags with action="create", '
                f'resource_type="spectroclusters", '
                f'uid="{_uid_or_unknown(s, "cluster_uid")}", and '
                f'tags=["{E2E_TEST_TAG}"]. '
                f'Confirm the tag "{E2E_TEST_TAG}" was added successfully.'
            ),
            required_tool="search_and_manage_resource_tags",
            required_action="create",
            required_resource_type="spectroclusters",
            judge_goal=f'"{E2E_TEST_TAG}" tag was added to the cluster without error.',
        ),
        # Step 9 — delete e2e tag from cluster profile, confirm via tags_after
        lambda s: E2ETestCase(
            name="delete_tag_from_cluster_profile",
            prompt=(
                f'Call search_and_manage_resource_tags with action="delete", '
                f'resource_type="clusterprofiles", '
                f'uid="{_uid_or_unknown(s, "profile_uid")}", and '
                f'tags=["{E2E_TEST_TAG}"]. '
                f'The delete response contains a "tags_after" field listing the tags remaining after deletion. '
                f'Confirm that "{E2E_TEST_TAG}" is NOT present in "tags_after".'
            ),
            required_tool="search_and_manage_resource_tags",
            required_action="delete",
            required_resource_type="clusterprofiles",
            judge_goal=f'"{E2E_TEST_TAG}" was deleted from the cluster profile and is absent from "tags_after" in the delete response.',
        ),
        # Step 10 — delete e2e tag from cluster, confirm via tags_after
        lambda s: E2ETestCase(
            name="delete_tag_from_cluster",
            prompt=(
                f'Call search_and_manage_resource_tags with action="delete", '
                f'resource_type="spectroclusters", '
                f'uid="{_uid_or_unknown(s, "cluster_uid")}", and '
                f'tags=["{E2E_TEST_TAG}"]. '
                f'The delete response contains a "tags_after" field listing the tags remaining after deletion. '
                f'Confirm that "{E2E_TEST_TAG}" is NOT present in "tags_after".'
            ),
            required_tool="search_and_manage_resource_tags",
            required_action="delete",
            required_resource_type="spectroclusters",
            judge_goal=f'"{E2E_TEST_TAG}" was deleted from the cluster and is absent from "tags_after" in the delete response.',
        ),
        # Step 11 — list cluster profiles to find to-be-deleted
        lambda _s: E2ETestCase(
            name="list_profiles_for_delete",
            prompt=(
                f'Call gather_or_delete_clusterprofiles with action="list". '
                f'Find the cluster profile named "{DELETE_CLUSTER_PROFILE_NAME}" '
                f"and confirm it is present. "
                f"End your response with exactly: DELETE_PROFILE_UID: <uid>"
            ),
            required_tool="gather_or_delete_clusterprofiles",
            required_action="list",
            required_resource_type=None,
            judge_goal=f'"{DELETE_CLUSTER_PROFILE_NAME}" is present in the list response and its UID is reported as DELETE_PROFILE_UID.',
        ),
        # Step 12 — delete to-be-deleted cluster profile
        lambda s: E2ETestCase(
            name="delete_cluster_profile",
            prompt=(
                f'Call gather_or_delete_clusterprofiles with action="delete" and '
                f'uid="{_uid_or_unknown(s, "delete_profile_uid")}". '
                f'Confirm the profile "{DELETE_CLUSTER_PROFILE_NAME}" was deleted successfully.'
            ),
            required_tool="gather_or_delete_clusterprofiles",
            required_action="delete",
            required_resource_type=None,
            judge_goal=f'"{DELETE_CLUSTER_PROFILE_NAME}" cluster profile was deleted successfully.',
        ),
        # Step 13 — list packs, find hello-universe by display name.
        lambda s: E2ETestCase(
            name="list_packs",
            prompt=(
                f'Call search_gather_packs with action="list" and pack_name="{HELLO_UNIVERSE_PACK_DISPLAY_NAME}". '
                f'Confirm that a pack with the name "{HELLO_UNIVERSE_PACK_NAME}" appears in the results. '
                f'Also confirm that the pack UID "{_uid_or_unknown(s, "hello_universe_pack_uid")}" appears as a latestPackUid in at least one registry entry of the matching pack. '
                f"End your response with exactly: PACK_UID: <latestPackUid from the first registry entry of the matching pack>"
            ),
            required_tool="search_gather_packs",
            required_action="list",
            required_resource_type=None,
            judge_goal=(
                f'A pack named "{HELLO_UNIVERSE_PACK_NAME}" is present in the search results, '
                f'the expected Terraform UID is present as a latestPackUid, '
                f'and the first registry latestPackUid is reported as PACK_UID.'
            ),
        ),
        # Step 14 — get hello-universe pack by UID with full detail (compact=False).
        lambda s: E2ETestCase(
            name="get_pack",
            prompt=(
                f'Call search_gather_packs with action="get", '
                f'pack_uid="{_uid_or_unknown(s, "latest_pack_uid")}", and compact=False. '
                f'Confirm the pack name is "{HELLO_UNIVERSE_PACK_NAME}". '
                f'Confirm that the response includes a non-empty "packValues" array where at least one entry contains a non-empty "values" field (the YAML content). '
                f'Also confirm that at least one entry in "packValues" contains a non-empty "readme" field.'
            ),
            required_tool="search_gather_packs",
            required_action="get",
            required_resource_type=None,
            judge_goal=(
                f'Pack name "{HELLO_UNIVERSE_PACK_NAME}" is confirmed, '
                f'"packValues" is present and non-empty, at least one entry has a non-empty "values" (YAML), '
                f'and at least one entry has a non-empty "readme".'
            ),
        ),
        # Step 15 — delete cluster.
        lambda s: E2ETestCase(
            name="delete_cluster",
            prompt=(
                f'Call gather_or_delete_clusters with action="delete" and '
                f'uid="{_uid_or_unknown(s, "cluster_uid")}". '
                f"Confirm the cluster was deleted successfully."
            ),
            required_tool="gather_or_delete_clusters",
            required_action="delete",
            required_resource_type=None,
            judge_goal="Cluster was deleted successfully.",
        ),
    ]


# ---------------------------------------------------------------------------
# Per-step judge
# ---------------------------------------------------------------------------


def judge_test_case(
    test_case: E2ETestCase, tool_summary: str, agent_output: str
) -> tuple[bool, str]:
    """Judge a single test case: verify the required tool call was made and the goal achieved."""
    required_call = f"{test_case.required_tool}(action={test_case.required_action}"
    if test_case.required_resource_type:
        required_call += f", resource_type={test_case.required_resource_type}"
    required_call += ")"

    prompt = f"""You are verifying ONE test step in an end-to-end test of a Palette MCP server.

Required tool call: {required_call}
Goal: {test_case.judge_goal}

Tool calls made by agent:
{tool_summary}

Agent output:
{agent_output}

A step PASSES when BOTH hold:
1. The required tool call appears in the tool summary with status OK (tool name, action, and resource_type must all match).
2. The goal was achieved — confirmed by the response snippet AND/OR the agent output.

Important: API responses can be large and the response snippet may be truncated.
If the agent output explicitly states a fact (e.g. "the profile name is X", "the tag is absent"),
accept that as sufficient evidence even when the raw snippet does not show it.

A step FAILS if the required call is missing, uses wrong arguments, returned ERROR, or the goal was not met.

Respond with exactly one of:
VERDICT: PASS
Reason: <one sentence>

or

VERDICT: FAIL
Reason: <one sentence explaining what was missing or wrong>"""

    response = OpenAI().chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    verdict_text = (response.choices[0].message.content or "").strip()
    passed = verdict_text.startswith("VERDICT: PASS")
    return passed, verdict_text


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    # 1. Register the KinD cluster with Palette, get the UID from terraform output.
    cluster_uid = setup_kubectl()
    hello_universe_pack_uid = get_hello_universe_pack_uid_from_terraform()

    # 2. Wait for the cluster to reach Running state before launching the agent.
    wait_for_cluster_running(cluster_uid)

    # 3. Prepare shared components.
    server_params = build_mcp_server_params()
    model = OpenAIModel(model_id=E2E_MODEL)
    results: list[E2ETestResult] = []

    # Shared state: UIDs discovered by earlier steps and passed to later ones.
    # cluster_uid and hello_universe_pack_uid are pre-populated from terraform output.
    state: dict[str, str | None] = {
        "profile_uid": None,
        "cluster_uid": cluster_uid,
        "delete_profile_uid": None,
        "hello_universe_pack_uid": hello_universe_pack_uid,
        "latest_pack_uid": None,
    }

    print(f"\nStarting e2e tests | model={E2E_MODEL} | image={MCP_DOCKER_IMAGE}\n")

    # 4. Run each test case as an isolated agent call inside a single MCP session.
    with ToolCollection.from_mcp(
        server_params, trust_remote_code=True, structured_output=False
    ) as tool_collection:
        fix_tool_schemas(tool_collection.tools)
        tools = [*tool_collection.tools]

        for step_factory in build_test_case_factories():
            test_case = step_factory(state)
            print(f"\n--- {test_case.name} ---")

            agent = ToolCallingAgent(
                tools=tools,
                model=model,
                max_steps=5,
                step_callbacks=[make_step_callback()],
                verbosity_level=0,
            )
            try:
                agent_output = str(
                    agent.run(AGENT_SYSTEM_PROMPT + "\n\n" + test_case.prompt)
                )
            except Exception as exc:
                agent_output = f"AGENT ERROR: {exc}"

            tool_summary = extract_tool_summary(agent)
            passed, verdict = judge_test_case(test_case, tool_summary, agent_output)
            results.append(
                E2ETestResult(
                    name=test_case.name,
                    passed=passed,
                    tool_summary=tool_summary,
                    agent_output=agent_output,
                    judge_verdict=verdict,
                )
            )
            print(f"  {'PASS' if passed else 'FAIL'} — {verdict}")

            # Update shared state from discovery steps.
            if passed:
                if test_case.name == "list_cluster_profiles":
                    state["profile_uid"] = extract_uid(agent_output, "PROFILE_UID")
                elif test_case.name == "list_profiles_for_delete":
                    state["delete_profile_uid"] = extract_uid(
                        agent_output, "DELETE_PROFILE_UID"
                    )
                elif test_case.name == "list_packs":
                    state["latest_pack_uid"] = extract_uid(agent_output, "PACK_UID")

    # 5. Print summary table.
    print("\n--- E2E Test Results ---")
    print(f"| {'#':<4} | {'Test':<42} | Status |")
    print(f"|{'-' * 6}|{'-' * 44}|--------|")
    for i, r in enumerate(results, 1):
        print(f"| {i:<4} | {r.name:<42} | {'PASS' if r.passed else 'FAIL'} |")

    failed = [r for r in results if not r.passed]
    if failed:
        print(f"\nE2E TESTS FAILED: {len(failed)}/{len(results)} steps failed")
        sys.exit(1)

    print("\nAll e2e tests passed.")


if __name__ == "__main__":
    main()
