---
title: "Blog App: Overview"
description: A multi-user blog API with role-based moderation and author ownership rules.
---

# Blog App: Overview

A multi-user blog API with role-based moderation and author ownership rules.

## Features

- User registration and login with password auth
- Role-based access: `admin`, `moderator`, `user`
- Role hierarchy: admin includes moderator, moderator includes user
- Public read access for posts and comments
- Authenticated write access with author-ownership rules
- Moderators can edit or delete any post
- Admin-only user management
- Natural-key country entity to demonstrate `pk:`

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| `user` | auth | Site members with password login and roles |
| `post` | data | Blog posts owned by authors |
| `country` | data | Country reference data with natural key |

## Endpoints

### Auth
| Method | Path | Access |
|--------|------|--------|
| POST | /users/register | public |
| POST | /users/login | public |

### Users
| Method | Path | Access |
|--------|------|--------|
| GET | /users | `*` (any auth) |
| GET | /users/{id} | `*` |
| PATCH | /users/{id} | `*` |
| DELETE | /users/{id} | owner or admin |

### Posts
| Method | Path | Access |
|--------|------|--------|
| GET | /posts | public |
| GET | /posts/{id} | public |
| POST | /posts | `*` |
| PATCH | /posts/{id} | author or moderator |
| DELETE | /posts/{id} | author or moderator |
| POST | /posts/{id}/publish | author or moderator |

### Countries
| Method | Path | Access |
|--------|------|--------|
| GET | /countries | public |
| GET | /countries/{code} | public |
| POST | /countries | admin |
| PATCH | /countries/{code} | admin |
| DELETE | /countries/{code} | admin |
