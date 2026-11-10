output "instance_id" {
  description = "Dev machine instance ID (used as the SSH host name over SSM)."
  value       = aws_instance.devbox.id
}

output "region" {
  value = var.region
}

output "ssh_config" {
  description = "Paste into ~/.ssh/config."
  value       = <<-EOT
    Host sentinel-devbox
      HostName ${aws_instance.devbox.id}
      User ubuntu
      IdentityFile ~/.ssh/id_ed25519
      ProxyCommand sh -c "aws ssm start-session --region ${var.region} --target %h --document-name AWS-StartSSHSession --parameters portNumber=%p"
      ServerAliveInterval 60
  EOT
}
