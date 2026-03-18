# Access Control Design

> **DEPRECATED (P8 SP5 / Session 32):** `src/auth/access_control.py` has been replaced by `src/settings/SettingsManager`. Per-agent permissions are now managed via the Dashboard Settings tab and stored in `~/.corerag/settings.yaml`. The RBAC scaffold described below is historical design documentation only.
>
> See `src/settings/settings_manager.py` for the current implementation. The entry point is `check_permissions()` in `src/server.py` (replaced `verify_api_key()`).

> **Status**: ⚠️ Historical — `src/auth/access_control.py` is DEPRECATED | See `src/settings/` for current implementation

## Overview

While the CoreRag system is primarily single-user, this document outlines access control for:
- Future multi-user scenarios
- Shared knowledge bases
- API access control
- Privacy tier enforcement

---

## Single-User Model (Current)

### Local-Only Access

```
┌─────────────────────────────────────────┐
│              Local Machine              │
│                                         │
│   ┌─────────┐      ┌─────────────────┐  │
│   │  User   │──────│   CoreRag    │  │
│   │ (Owner) │      │   (Full Access) │  │
│   └─────────┘      └─────────────────┘  │
│                                         │
└─────────────────────────────────────────┘
```

### Privacy Tiers as Access Control

Even for single-user, privacy tiers control what's exposed:

```python
class PrivacyTier:
    PUBLIC = "public"      # Can share, export
    INTERNAL = "internal"  # Work-related
    PRIVATE = "private"    # Personal
    SENSITIVE = "sensitive" # PII, financial
    RESTRICTED = "restricted" # Requires password
```

### Tier Enforcement

```python
class AccessController:
    def can_share(self, doc, tier):
        """Check if document can be shared externally."""
        return tier in [PrivacyTier.PUBLIC]

    def can_export(self, doc, tier):
        """Check if document can be exported."""
        return tier in [PrivacyTier.PUBLIC, PrivacyTier.INTERNAL]

    def can_include_in_context(self, doc, tier):
        """Check if document can be sent to Claude."""
        # Sensitive/restricted content not sent to API
        return tier not in [PrivacyTier.SENSITIVE, PrivacyTier.RESTRICTED]

    def requires_password(self, doc, tier):
        """Check if access requires password."""
        return tier == PrivacyTier.RESTRICTED
```

---

## Multi-User Model (Future)

### User Roles

```python
class UserRole(Enum):
    OWNER = "owner"       # Full control
    ADMIN = "admin"       # Manage users, settings
    EDITOR = "editor"     # Add/edit documents
    VIEWER = "viewer"     # Read-only access
    GUEST = "guest"       # Limited read-only
```

### Permissions Matrix

| Action | Owner | Admin | Editor | Viewer | Guest |
|--------|-------|-------|--------|--------|-------|
| View public docs | ✅ | ✅ | ✅ | ✅ | ✅ |
| View private docs | ✅ | ✅ | ✅ | ✅ | ❌ |
| View sensitive | ✅ | ✅ | ❌ | ❌ | ❌ |
| View restricted | ✅ | ❌ | ❌ | ❌ | ❌ |
| Add documents | ✅ | ✅ | ✅ | ❌ | ❌ |
| Edit documents | ✅ | ✅ | ✅ | ❌ | ❌ |
| Delete documents | ✅ | ✅ | ❌ | ❌ | ❌ |
| Manage tags | ✅ | ✅ | ✅ | ❌ | ❌ |
| Manage users | ✅ | ✅ | ❌ | ❌ | ❌ |
| System settings | ✅ | ✅ | ❌ | ❌ | ❌ |
| Export all | ✅ | ✅ | ❌ | ❌ | ❌ |
| API access | ✅ | ✅ | ✅ | ✅ | ❌ |

### User Model

```python
@dataclass
class User:
    user_id: str
    username: str
    email: str
    role: UserRole
    created_at: str
    last_login: Optional[str]
    permissions_override: Dict[str, bool] = field(default_factory=dict)
    allowed_tags: List[str] = field(default_factory=list)  # Tag-based access
    allowed_collections: List[str] = field(default_factory=list)
```

---

## API Access Control

### API Keys

```python
@dataclass
class APIKey:
    key_id: str
    key_hash: str  # Never store plaintext
    user_id: str
    name: str
    created_at: str
    expires_at: Optional[str]
    permissions: List[str]  # ["read", "write", "search"]
    rate_limit: int  # requests per minute
    allowed_ips: List[str]  # IP whitelist
```

### API Permissions

```python
class APIPermission(Enum):
    SEARCH = "search"           # Search documents
    READ = "read"               # Read document content
    WRITE = "write"             # Add/update documents
    DELETE = "delete"           # Delete documents
    ADMIN = "admin"             # Administrative actions
    EXPORT = "export"           # Bulk export
    CONTEXT = "context"         # Get context for LLM
```

### Rate Limiting per Key

```python
RATE_LIMITS = {
    "free": {
        "requests_per_minute": 10,
        "requests_per_day": 1000,
        "max_results": 10
    },
    "standard": {
        "requests_per_minute": 60,
        "requests_per_day": 10000,
        "max_results": 100
    },
    "unlimited": {
        "requests_per_minute": None,
        "requests_per_day": None,
        "max_results": None
    }
}
```

---

## Document-Level Access

### Access Control List (ACL)

```python
@dataclass
class DocumentACL:
    document_id: str
    owner_id: str
    visibility: str  # "public", "private", "shared"
    shared_with: List[str]  # user_ids
    shared_groups: List[str]  # group_ids
    permissions: Dict[str, List[str]]  # user_id -> ["read", "write"]
```

### Inheritance

```python
class ACLInheritance:
    """Documents can inherit access from collections."""

    def get_effective_access(self, user_id, document_id):
        # Check document-level ACL
        doc_acl = self.get_document_acl(document_id)
        if user_id in doc_acl.shared_with:
            return doc_acl.permissions[user_id]

        # Check collection-level ACL
        collections = self.get_document_collections(document_id)
        for collection in collections:
            col_acl = self.get_collection_acl(collection.id)
            if user_id in col_acl.shared_with:
                return col_acl.permissions[user_id]

        # Check global role
        user = self.get_user(user_id)
        return self.get_role_permissions(user.role)
```

---

## Authentication (Future)

### Local Authentication

```python
class LocalAuth:
    """Password-based authentication for local access."""

    def authenticate(self, username: str, password: str) -> Optional[User]:
        user = self.get_user_by_username(username)
        if user and self.verify_password(password, user.password_hash):
            return user
        return None

    def hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt())
```

### Token-Based (for API)

```python
class TokenAuth:
    """JWT tokens for API access."""

    def create_token(self, user: User) -> str:
        payload = {
            "user_id": user.user_id,
            "role": user.role.value,
            "exp": datetime.utcnow() + timedelta(hours=24)
        }
        return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

    def verify_token(self, token: str) -> Optional[Dict]:
        try:
            return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return None
```

---

## Audit Logging

### Access Log

```python
@dataclass
class AccessLogEntry:
    timestamp: str
    user_id: str
    action: str  # "read", "write", "search", "delete"
    resource_type: str  # "document", "collection", "tag"
    resource_id: str
    ip_address: str
    user_agent: str
    success: bool
    details: Dict
```

### Sensitive Actions

Always log:
- Access to sensitive/restricted content
- Failed authentication attempts
- Permission changes
- Bulk exports
- API key creation/revocation

```python
class AuditLogger:
    ALWAYS_LOG = [
        "access_sensitive",
        "access_restricted",
        "auth_failure",
        "permission_change",
        "bulk_export",
        "api_key_change",
        "user_create",
        "user_delete"
    ]

    def log_access(self, entry: AccessLogEntry):
        if entry.action in self.ALWAYS_LOG or not entry.success:
            self.write_log(entry)
```

---

## Implementation Phases

### Phase 1: Privacy Tiers (Current)

- [x] Define privacy tiers
- [x] Privacy scanning on ingest
- [ ] Tier enforcement in search
- [ ] Tier enforcement in export
- [ ] Tier enforcement in MCP context

### Phase 2: API Access Control

- [ ] API key generation
- [ ] Key-based authentication
- [ ] Rate limiting
- [ ] Permission scoping

### Phase 3: Multi-User (Future)

- [ ] User accounts
- [ ] Role-based access
- [ ] Document ACLs
- [ ] Audit logging

---

## Security Best Practices

1. **Principle of Least Privilege**: Default to minimal access
2. **Defense in Depth**: Multiple layers of checks
3. **Secure Defaults**: New documents are private
4. **Audit Everything**: Log all sensitive actions
5. **Fail Closed**: Deny access on uncertainty
6. **Encryption at Rest**: Sensitive content encrypted
7. **Secure Transmission**: HTTPS/TLS for any network access
