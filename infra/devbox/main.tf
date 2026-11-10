data "aws_availability_zones" "available" {
  state = "available"
}

# Canonical publishes the current Ubuntu 24.04 AMI ID here; the image includes the SSM agent.
data "aws_ssm_parameter" "ubuntu" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

# ---------------------------------------------------------------------------
# Network: one public subnet, no NAT gateway (saves ~$32/month).
# The instance has a public IP for outbound traffic only; the security group
# allows no inbound traffic at all. Access is through SSM Session Manager.
# ---------------------------------------------------------------------------

resource "aws_vpc" "dev" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "sentinel-devbox" }
}

resource "aws_internet_gateway" "dev" {
  vpc_id = aws_vpc.dev.id
  tags   = { Name = "sentinel-devbox" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.dev.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 0)
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = { Name = "sentinel-devbox-public" }
}

# Our own route table, so the subnet's internet access never depends on
# (or changes) anything else in the account.
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.dev.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.dev.id
  }

  tags = { Name = "sentinel-devbox-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "devbox" {
  name        = "sentinel-devbox"
  description = "Dev machine: no inbound, all outbound"
  vpc_id      = aws_vpc.dev.id

  egress {
    description = "All outbound (package installs, image pulls, SSM, LLM APIs)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "sentinel-devbox" }
}

# ---------------------------------------------------------------------------
# IAM: the instance may only talk to SSM. Nothing else.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "devbox" {
  name = "sentinel-devbox"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.devbox.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "devbox" {
  name = "sentinel-devbox"
  role = aws_iam_role.devbox.name
}

# ---------------------------------------------------------------------------
# The dev machine
# ---------------------------------------------------------------------------

resource "aws_instance" "devbox" {
  ami                    = data.aws_ssm_parameter.ubuntu.value
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.devbox.id]
  iam_instance_profile   = aws_iam_instance_profile.devbox.name

  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    ssh_public_key = trimspace(var.ssh_public_key)
    bootstrap      = file("${path.module}/bootstrap.sh")
  })

  metadata_options {
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1          # containers cannot reach instance metadata
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    encrypted             = true
    delete_on_termination = true
  }

  tags = { Name = "sentinel-devbox" }

  lifecycle {
    # A newer Ubuntu AMI should not force a rebuild of a running dev machine.
    ignore_changes = [ami, user_data]
  }
}

# ---------------------------------------------------------------------------
# Cost guardrail: alerts for everything tagged Project=sentinel-desk.
# Note: the Project tag must be activated as a cost allocation tag
# (Billing -> Cost allocation tags) for the filter to match.
# ---------------------------------------------------------------------------

resource "aws_budgets_budget" "project" {
  name         = "sentinel-desk-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$sentinel-desk"]
  }

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
