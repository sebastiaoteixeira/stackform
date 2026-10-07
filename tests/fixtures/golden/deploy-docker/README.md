# my-api-service Deployment

This directory contains Docker deployment configuration for my-api-service.

## Prerequisites

- Docker and Docker Compose installed
- Git (for cloning the repository)

## Quick Start


### 1. Configure Environment Variables

Edit the `.env` file with your configuration:

```bash
```

### 2. Start Services

```bash
docker compose up -d
```

This will start:
- Backend API on port 8080

### 3. Check Status

```bash
docker compose ps
docker compose logs -f
```

## Services

- **app**: Backend API service (FastAPI)
  - Port: 8080
  - Built from: `backend/`



## Development

To rebuild after code changes:

```bash
docker compose build
docker compose up -d
```

## Production Deployment

For production deployment to a remote server:

```bash
ansible-playbook -i inventory.yml playbook.yml
```

Make sure to:
1. Update `inventory.yml` with your server details
2. Configure SSH keys for authentication
3. Set production environment variables

## Hardening: encrypt secrets at rest with ansible-vault

By default, secrets are generated during the build and written to the local
`.env` file in plaintext, and `docker-compose.yml` reads them as `${VAR}`. This
is convenient but leaves secrets unencrypted on the control node and unsafe to
commit. When you need secrets encrypted at rest in source control, `ansible-vault`
is the opt-in upgrade path.

1. Move the sensitive entries from `.env` into `group_vars/all/secrets.yml`
   (Ansible auto-loads this file for every host):

   ```yaml
   ```

2. Encrypt the file so it is safe to commit:

   ```bash
   ansible-vault encrypt group_vars/all/secrets.yml
   ```

3. Supply the vault password when running the playbook:

   ```bash
   ansible-playbook -i inventory.yml playbook.yml --ask-vault-pass
   # unattended runs can read the password from a file instead:
   ansible-playbook -i inventory.yml playbook.yml --vault-password-file .vault-pass
   ```

Deploy-time generation remains the default; enable vault only when you need
secrets encrypted at rest.

## Stopping Services

```bash
docker compose down
```

To also remove volumes:

```bash
docker compose down -v
```

## Troubleshooting

### Backend won't start

Check logs:
```bash
docker compose logs app
```

Common issues:
- Missing environment variables: Check `.env` file
- Port already in use: Change port in docker-compose.yml


### Database connection errors

- Check your external MongoDB connection string in `.env`
- Ensure network connectivity from container to MongoDB
