variable "tags" {
  type    = list(string)
  default = ["owner:ai-research-team", "terraform_managed:true"]
}

variable "api_key" {
  type        = string
  description = "The API key for the Palette API"
}

variable "project_name" {
  type        = string
  description = "The name of the project to use for the Palette API"
}
