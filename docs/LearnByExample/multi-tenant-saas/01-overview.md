# Multi-Tenant SaaS: Overview

A SaaS API with users, organizations, and per-organization roles. Users belong to one or more organizations with different roles in each.

## Features

- User registration and login with password auth
- Organizations as first-class entities
- Organization membership via a `member` join entity
- Per-organization roles: `owner`, `admin`, `member`
- Role hierarchy within organizations
- External API clients with API key auth (separate auth entity)
- Resources scoped to organizations

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| `user` | auth | Human users with password login |
| `apiClient` | auth | Machine-to-machine clients with API key auth |
| `org` | data | An organization (tenant) |
| `membership` | data | User-org relationship with per-org role |
| `resource` | data | A resource owned by an org |

## Auth entities

This app has two auth entities: `user` and `apiClient`. Because of this, access rules must use the entity prefix (`user:admin`, `apiClient:enterprise`) — unscoped role names are not allowed.

## Endpoints

### Auth
| Method | Path | Access |
|--------|------|--------|
| POST | /users/register | public |
| POST | /users/login | public |

### Orgs
| Method | Path | Access |
|--------|------|--------|
| GET | /orgs | `*` |
| GET | /orgs/{id} | `*` |
| POST | /orgs | `user:*` |
| PATCH | /orgs/{id} | org owner |
| DELETE | /orgs/{id} | org owner |

### Resources
| Method | Path | Access |
|--------|------|--------|
| GET | /resources | `*` |
| GET | /resources/{id} | `*` |
| POST | /resources | org member or apiClient |
| PATCH | /resources/{id} | org admin or apiClient:enterprise |
| DELETE | /resources/{id} | org owner |

## Multi-entity access design

With two auth entities, all role references require entity scoping:

```yaml
access: user:*         # any human user
access: apiClient:*    # any API client
access: [user:*, apiClient:*]  # either
access: user:owner     # org owner (user entity role)
access: apiClient:enterprise   # enterprise API client tier
```
