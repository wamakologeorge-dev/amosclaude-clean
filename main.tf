# File: main.tf

# Configure the AWS Provider
provider "aws" {
  region = "us-west-2"
}

# Create an S3 Bucket for the platform's root domain
resource "aws_s3_bucket" "root_domain" {
  bucket = "your-repo-name.your-username.github.io"
  acl    = "public-read"

  website {
    index_document = "index.html"
  }
}

# Create an S3 Bucket for the platform's repository domain
resource "aws_s3_bucket" "repo_domain" {
  bucket = "your-repo-name.your-username.github.io/repo"
  acl    = "public-read"

  website {
    index_document = "index.html"
  }
}

# Create a Route 53 Hosted Zone for the platform's root domain
resource "aws_route53_zone" "root_domain" {
  name = "your-repo-name.your-username.github.io."
}

# Create a Route 53 Record Set for the platform's root domain
resource "aws_route53_record" "root_domain" {
  zone_id = aws_route53_zone.root_domain.zone_id
  name    = "your-repo-name.your-username.github.io"
  type    = "A"
  alias {
    name                   = aws_s3_bucket.root_domain.website_endpoint
    zone_id                = aws_s3_bucket.root_domain.zone_id
    evaluate_target_health = false
  }
}

# Create a Route 53 Record Set for the platform's repository domain
resource "aws_route53_record" "repo_domain" {
  zone_id = aws_route53_zone.root_domain.zone_id
  name    = "your-repo-name.your-username.github.io/repo"
  type    = "A"
  alias {
    name                   = aws_s3_bucket.repo_domain.website_endpoint
    zone_id                = aws_s3_bucket.repo_domain.zone_id
    evaluate_target_health = false
  }
}
