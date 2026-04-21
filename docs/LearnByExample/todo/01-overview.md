# Todo App: Overview

A multi-user todo API where each user owns their own lists and items.

## Features

- User registration and login with password auth
- Each user has private todo lists
- Each list contains items
- Users can only access their own lists and items
- No cross-user visibility (no admin role, no shared lists)

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| `user` | auth | App users with password login |
| `list` | data | A named collection of todos, owned by a user |
| `item` | data | A single todo item belonging to a list |

## Endpoints

### Auth
| Method | Path | Access |
|--------|------|--------|
| POST | /users/register | public |
| POST | /users/login | public |

### Lists
| Method | Path | Access |
|--------|------|--------|
| GET | /lists | owner only |
| GET | /lists/{id} | owner only |
| POST | /lists | `*` (authenticated) |
| PATCH | /lists/{id} | owner only |
| DELETE | /lists/{id} | owner only |

### Items
| Method | Path | Access |
|--------|------|--------|
| GET | /items | owner only (via list ownership) |
| GET | /items/{id} | owner only |
| POST | /items | `*` (authenticated) |
| PATCH | /items/{id} | owner only |
| DELETE | /items/{id} | owner only |

## Key design decisions

- `list.ownerId` links lists to users. Access rules on list operations check `principal.sub equals document.ownerId`.
- `item.listId` links items to their list. Item access checks `principal.sub equals document.ownerId` (items also store `ownerId` directly for efficient authorization).
- No roles needed — all access is purely ownership-based.
