# RBAC Groups + User Autocomplete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add workspace group-based role assignments and fix user autocomplete dropdown for RBAC management.

**Architecture:** New `group_roles` Lakebase table stores group→role mappings. SCIM calls use the SP token (not OBO) to avoid scope limitations. `resolve_role` checks user→group→default priority with highest-privilege-wins for groups. Frontend adds group management section mirroring the existing user section.

**Tech Stack:** FastAPI, asyncpg (Lakebase), SCIM v2 API, React

---

### Task 1: Group roles DB layer

**Files:**
- Modify: `backend/app/services/storage_pgvector.py` (add group_roles table + CRUD)
- Modify: `backend/app/services/database.py` (delegate group role methods)

- [ ] **Step 1: Add `_ensure_group_roles_table` to PGVectorStorageService**

In `storage_pgvector.py`, after `_ensure_user_roles_table`:

```python
async def _ensure_group_roles_table(self, conn):
    """Create the group_roles table if it does not exist."""
    await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {self.schema_prefix}.group_roles (
            group_name TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            granted_by TEXT,
            granted_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    logger.info("Group roles table '%s.group_roles' initialized", self.schema_prefix)
```

Call it from `_ensure_tables` after `_ensure_user_roles_table` (line ~199):
```python
await self._ensure_group_roles_table(conn)
```

Also add `self.group_roles_table_name = f"{schema_prefix}.group_roles"` in `__init__`.

- [ ] **Step 2: Add group role CRUD methods to PGVectorStorageService**

```python
async def get_group_role(self, group_name: str) -> str | None:
    async with self.pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT role FROM {self.group_roles_table_name} WHERE group_name = $1",
            group_name
        )
        return row["role"] if row else None

async def set_group_role(self, group_name: str, role: str, granted_by: str = None):
    async with self.pool.acquire() as conn:
        await conn.execute(f"""
            INSERT INTO {self.group_roles_table_name} (group_name, role, granted_by, granted_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (group_name) DO UPDATE SET role = $2, granted_by = $3, granted_at = NOW()
        """, group_name, role, granted_by)

async def list_group_roles(self) -> list:
    async with self.pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT group_name, role, granted_by, granted_at FROM {self.group_roles_table_name} ORDER BY granted_at DESC"
        )
        return [dict(r) for r in rows]

async def delete_group_role(self, group_name: str):
    async with self.pool.acquire() as conn:
        await conn.execute(
            f"DELETE FROM {self.group_roles_table_name} WHERE group_name = $1",
            group_name
        )
```

- [ ] **Step 3: Delegate group role methods in DynamicStorageService**

In `database.py`, add after `count_owners`:

```python
async def get_group_role(self, group_name: str):
    return await self.backend.get_group_role(group_name)

async def set_group_role(self, group_name: str, role: str, granted_by: str = None):
    return await self.backend.set_group_role(group_name, role, granted_by)

async def list_group_roles(self) -> list:
    return await self.backend.list_group_roles()

async def delete_group_role(self, group_name: str):
    return await self.backend.delete_group_role(group_name)
```

- [ ] **Step 4: Commit**

```
git add backend/app/services/storage_pgvector.py backend/app/services/database.py
git commit -m "feat(rbac): add group_roles table and CRUD methods"
```

---

### Task 2: SCIM service — SP token + group membership + groups listing

**Files:**
- Modify: `backend/app/services/rbac.py` (add SP-based SCIM helpers, group membership lookup)

- [ ] **Step 1: Add `_get_sp_token` helper and `get_user_groups` function**

At the top of `rbac.py`, add a helper that gets the SP token for SCIM calls:

```python
def _get_sp_token() -> str:
    """Get the app's service principal token for SCIM calls."""
    from app.auth import get_service_principal_token
    return get_service_principal_token() or ""
```

Add group membership lookup with cache:

```python
_GROUP_CACHE_TTL = 60.0
_GROUP_CACHE_MAX = 500
_group_cache: dict[str, tuple[list[str], float]] = {}  # email → ([group_names], expires_at)


def _sweep_expired_group_cache():
    now = time.monotonic()
    expired = [k for k, (_, exp) in _group_cache.items() if now >= exp]
    for k in expired:
        del _group_cache[k]
    if len(_group_cache) > _GROUP_CACHE_MAX:
        by_expiry = sorted(_group_cache.items(), key=lambda kv: kv[1][1])
        for k, _ in by_expiry[:len(_group_cache) - _GROUP_CACHE_MAX]:
            del _group_cache[k]


async def get_user_groups(email: str, host: str) -> list[str]:
    """Return display names of groups the user belongs to via SCIM.
    Uses the SP token (not user OBO) to avoid scope limitations.
    """
    if not email or not host:
        return []
    if not _EMAIL_RE.match(email):
        return []

    now = time.monotonic()
    if len(_group_cache) > _GROUP_CACHE_MAX:
        _sweep_expired_group_cache()

    cached = _group_cache.get(email)
    if cached is not None:
        groups, expires_at = cached
        if now < expires_at:
            return groups

    host = ensure_https(host)
    token = _get_sp_token()
    if not token:
        return []

    groups = []
    try:
        resp = await _http_client.get(
            f"{host}/api/2.0/preview/scim/v2/Users",
            headers={"Authorization": f"Bearer {token}"},
            params={"filter": f'userName eq "{email}"', "attributes": "groups"},
        )
        if resp.status_code == 200:
            resources = resp.json().get("Resources", [])
            if resources:
                groups = [
                    g.get("display", "")
                    for g in resources[0].get("groups", [])
                    if g.get("display")
                ]
    except Exception as e:
        logger.warning("Failed to fetch groups for %s: %s", email, e)

    _group_cache[email] = (groups, now + _GROUP_CACHE_TTL)
    return groups
```

- [ ] **Step 2: Add `list_workspace_groups` for discovery endpoint**

```python
async def list_workspace_groups(host: str) -> list[dict]:
    """List all workspace groups via SCIM using the SP token."""
    token = _get_sp_token()
    if not token or not host:
        return []
    host = ensure_https(host)

    all_groups = []
    start_index = 1
    page_size = 500
    try:
        while True:
            resp = await _http_client.get(
                f"{host}/api/2.0/preview/scim/v2/Groups",
                headers={"Authorization": f"Bearer {token}"},
                params={"count": page_size, "startIndex": start_index, "attributes": "displayName,members"},
            )
            if resp.status_code != 200:
                logger.warning("SCIM Groups API returned %d", resp.status_code)
                break
            data = resp.json()
            resources = data.get("Resources", [])
            for g in resources:
                name = g.get("displayName", "")
                if name:
                    all_groups.append({
                        "displayName": name,
                        "memberCount": len(g.get("members", [])),
                    })
            total = data.get("totalResults", 0)
            if start_index + page_size > total or not resources:
                break
            start_index += page_size
    except Exception as e:
        logger.warning("Failed to list workspace groups: %s", e)

    return all_groups
```

- [ ] **Step 3: Update `is_workspace_admin` to use SP token fallback**

Change `is_workspace_admin` to fall back to SP-based lookup when user token fails:

In the existing function, after the current SCIM /Me call fails or token is empty, add SP fallback. Actually, simpler: change `is_workspace_admin` to accept an `identity` parameter and use SP token to look up by email when user token is empty:

Replace the existing function signature and body with:

```python
async def is_workspace_admin(token: str, host: str, identity: str = "") -> bool:
    """Check if the token owner is a Databricks workspace admin via SCIM.
    When token is empty but identity is provided, uses SP token to look up by email.
    """
    if not host:
        return False
    host = ensure_https(host)

    # Determine which token and endpoint to use
    lookup_token = token
    use_me_endpoint = bool(token)

    if not lookup_token and identity:
        lookup_token = _get_sp_token()
        use_me_endpoint = False

    if not lookup_token:
        return False

    now = time.monotonic()
    cache_key = token or identity
    if len(_admin_cache) > _ADMIN_CACHE_MAX:
        _sweep_expired_admin_cache()

    cached = _admin_cache.get(cache_key)
    if cached is not None:
        result, expires_at = cached
        if now < expires_at:
            return result

    result = False
    try:
        if use_me_endpoint:
            resp = await _http_client.get(
                f"{host}/api/2.0/preview/scim/v2/Me",
                headers={"Authorization": f"Bearer {lookup_token}"}
            )
            if resp.status_code == 200:
                groups = resp.json().get("groups", [])
                result = any(g.get("display") == "admins" for g in groups)
        elif identity and _EMAIL_RE.match(identity):
            resp = await _http_client.get(
                f"{host}/api/2.0/preview/scim/v2/Users",
                headers={"Authorization": f"Bearer {lookup_token}"},
                params={"filter": f'userName eq "{identity}"', "attributes": "groups"},
            )
            if resp.status_code == 200:
                resources = resp.json().get("Resources", [])
                if resources:
                    groups = resources[0].get("groups", [])
                    result = any(g.get("display") == "admins" for g in groups)
    except Exception as e:
        logger.warning("Workspace admin check failed: %s", e)

    _admin_cache[cache_key] = (result, now + _ADMIN_CACHE_TTL)
    return result
```

- [ ] **Step 4: Update `resolve_role` to check group memberships**

```python
async def resolve_role(identity: str, token: str, host: str) -> str:
    import app.services.database as _db

    if await is_workspace_admin(token, host, identity=identity):
        return 'owner'

    if not identity:
        return DEFAULT_ROLE

    now = time.monotonic()
    cached = _role_cache.get(identity)
    if cached is not None:
        role, expires_at = cached
        if now < expires_at:
            return role

    # 1. Explicit user role
    assigned = None
    if _db.db_service:
        assigned = await _db.db_service.get_user_role(identity)

    if assigned:
        role = assigned
    else:
        # 2. Highest group role
        role = DEFAULT_ROLE
        if _db.db_service:
            user_groups = await get_user_groups(identity, host)
            if user_groups:
                for g in user_groups:
                    g_role = await _db.db_service.get_group_role(g)
                    if g_role and ROLE_HIERARCHY.get(g_role, 0) > ROLE_HIERARCHY.get(role, 0):
                        role = g_role

    if len(_role_cache) > _ROLE_CACHE_MAX:
        _sweep_expired_role_cache()
    _role_cache[identity] = (role, now + _ROLE_CACHE_TTL)
    return role
```

- [ ] **Step 5: Update callers of `is_workspace_admin`**

In `rbac_routes.py`, update calls to pass `identity`:
- Line 141: `caller_is_admin = await is_workspace_admin(token, host, identity=identity) if host else False`
- Line 175: same pattern

In `auth_helpers.py` `require_role`, line 129:
```python
role = await resolve_role(identity, token, host)
```
No change needed — `resolve_role` passes identity through to `is_workspace_admin`.

- [ ] **Step 6: Also export new functions and invalidate group cache on write**

Add `invalidate_group_cache` to `rbac.py`:
```python
def invalidate_group_cache():
    """Clear group-related caches after group role changes."""
    _group_cache.clear()
    _role_cache.clear()
```

Export `get_user_groups`, `list_workspace_groups`, `invalidate_group_cache` from the module.

- [ ] **Step 7: Commit**

```
git add backend/app/services/rbac.py backend/app/api/rbac_routes.py
git commit -m "feat(rbac): SP-based SCIM, group membership lookup, resolve_role with groups"
```

---

### Task 3: Group RBAC API endpoints

**Files:**
- Modify: `backend/app/api/rbac_routes.py` (add group endpoints)
- Modify: `backend/app/api/gateway_routes.py` (add workspace groups discovery)

- [ ] **Step 1: Add group CRUD endpoints to `rbac_routes.py`**

After the existing user endpoints, add:

```python
@rbac_router.get("/groups")
async def list_groups(req: Request):
    """List all group role assignments. Manage or above."""
    await require_role(req, "manage")
    import app.services.database as _db
    if not _db.db_service:
        raise HTTPException(status_code=503, detail="RBAC requires Lakebase.")
    return await _db.db_service.list_group_roles()


@rbac_router.post("/groups/{group_name}/role", status_code=200)
async def assign_group_role(group_name: str, body: RoleAssignment, req: Request):
    """Assign a role to a workspace group. Manage or above."""
    identity, _, caller_role = await require_role(req, "manage")
    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role '{body.role}'. Valid: {ROLES}")
    if not role_gte(caller_role, body.role):
        raise HTTPException(status_code=403, detail=f"Cannot assign role '{body.role}' — your role ('{caller_role}') is insufficient.")
    import app.services.database as _db
    if not _db.db_service:
        raise HTTPException(status_code=503, detail="RBAC requires Lakebase.")
    await _db.db_service.set_group_role(group_name, body.role, granted_by=identity)
    invalidate_group_cache()
    logger.info("Group role assigned: %s → %s by %s", group_name, body.role, identity)
    return {"group_name": group_name, "role": body.role, "granted_by": identity}


@rbac_router.delete("/groups/{group_name}")
async def remove_group_role(group_name: str, req: Request):
    """Remove group role assignment. Manage or above."""
    identity, _, _ = await require_role(req, "manage")
    import app.services.database as _db
    if not _db.db_service:
        raise HTTPException(status_code=503, detail="RBAC requires Lakebase.")
    await _db.db_service.delete_group_role(group_name)
    invalidate_group_cache()
    logger.info("Group role removed: %s by %s", group_name, identity)
    return {"success": True}
```

Add `invalidate_group_cache` to the import from `app.services.rbac`.

- [ ] **Step 2: Add workspace groups discovery to `gateway_routes.py`**

After the `list_workspace_users` endpoint:

```python
@gateway_router.get("/workspace/groups")
async def list_workspace_groups_endpoint(req: Request):
    """List workspace groups via SCIM for group role assignment."""
    await require_role(req, "manage")
    from app.services.rbac import list_workspace_groups
    host = _get_host()
    groups = await list_workspace_groups(host)
    return {"groups": groups}
```

- [ ] **Step 3: Update workspace users endpoint to use SP token**

In `gateway_routes.py` `list_workspace_users`, change the token resolution to prefer SP token for SCIM:

```python
from app.services.rbac import _get_sp_token
token = _get_sp_token() or resolve_user_token_optional(req)
```

This fixes the autocomplete not working when OBO token lacks SCIM scope.

- [ ] **Step 4: Commit**

```
git add backend/app/api/rbac_routes.py backend/app/api/gateway_routes.py
git commit -m "feat(rbac): group role CRUD endpoints, workspace groups discovery, SP token for SCIM"
```

---

### Task 4: Frontend API client + Groups UI

**Files:**
- Modify: `frontend/src/services/api.js` (add group API methods)
- Modify: `frontend/src/components/settings/SettingsPage.jsx` (add groups section, fix sidebar)

- [ ] **Step 1: Add group API methods to `api.js`**

After `listWorkspaceUsers`, add:

```javascript
listGroups: async () => {
  const response = await axios.get(`${API_BASE_URL}/groups`);
  return response.data;
},

setGroupRole: async (groupName, role) => {
  const response = await axios.post(`${API_BASE_URL}/groups/${encodeURIComponent(groupName)}/role`, { role });
  return response.data;
},

deleteGroupRole: async (groupName) => {
  const response = await axios.delete(`${API_BASE_URL}/groups/${encodeURIComponent(groupName)}`);
  return response.data;
},

listWorkspaceGroups: async () => {
  const response = await axios.get(`${API_BASE_URL}/workspace/groups`);
  return response.data.groups || [];
},
```

- [ ] **Step 2: Add Groups section to sidebar and state**

In `SettingsPage.jsx`, update `SIDEBAR_MANAGE`:

```javascript
const SIDEBAR_MANAGE = [
  { category: 'Access Control', icon: Users, items: [
    { id: 'users', label: 'Users' },
    { id: 'groups', label: 'Groups' },
  ]},
]
```

Add group state variables alongside the user ones:

```javascript
const [groups, setGroups] = useState([])
const [groupsLoading, setGroupsLoading] = useState(false)
const [groupError, setGroupError] = useState(null)
const [newGroupName, setNewGroupName] = useState('')
const [newGroupRole, setNewGroupRole] = useState('use')
const [groupSaving, setGroupSaving] = useState(false)
const [workspaceGroups, setWorkspaceGroups] = useState([])
const [showGroupDropdown, setShowGroupDropdown] = useState(false)
```

- [ ] **Step 3: Add group data loading effect**

After the existing users loading effect:

```javascript
useEffect(() => {
  if (isManage && activeSection === 'groups') {
    setGroupsLoading(true)
    Promise.all([
      api.listGroups().catch(() => []),
      api.listWorkspaceGroups().catch(() => []),
    ]).then(([roleGroups, wsGroups]) => {
      setGroups(roleGroups)
      setWorkspaceGroups(wsGroups)
    }).finally(() => setGroupsLoading(false))
  }
}, [isManage, activeSection])
```

- [ ] **Step 4: Add group handlers**

```javascript
const handleAddGroup = async () => {
  if (!newGroupName.trim()) return
  setGroupSaving(true)
  setGroupError(null)
  try {
    const saved = await api.setGroupRole(newGroupName.trim(), newGroupRole)
    setGroups(prev => {
      const without = prev.filter(g => g.group_name !== saved.group_name)
      return [...without, saved]
    })
    setNewGroupName('')
    setNewGroupRole('use')
  } catch (err) {
    setGroupError(err.response?.data?.detail || 'Failed to assign group role.')
  } finally { setGroupSaving(false) }
}

const handleRemoveGroup = async (groupName) => {
  if (!window.confirm(`Remove role for group "${groupName}"?`)) return
  setGroupError(null)
  try {
    await api.deleteGroupRole(groupName)
    setGroups(prev => prev.filter(g => g.group_name !== groupName))
  } catch (err) {
    setGroupError(err.response?.data?.detail || 'Failed to remove group role.')
  }
}
```

- [ ] **Step 5: Add Groups section JSX**

After the Users section (`{isManage && ...}`), add the Groups section. It mirrors the Users section structure:

```jsx
{isManage && (
  <div ref={el => sectionRefs.current['groups'] = el} className="mb-10">
    <h2 className="text-[22px] font-semibold text-dbx-text leading-[28px] pb-3 border-b border-dbx-border">Groups</h2>

    <div className="py-4 text-[12px] text-dbx-text-secondary">
      Assign roles to workspace groups. When a user belongs to multiple groups, the highest privilege wins.
    </div>

    {groupError && (
      <div className="mb-3 px-3 py-2 rounded bg-red-50 border border-red-200 text-red-700 text-[13px]">
        {groupError}
      </div>
    )}

    {groupsLoading ? (
      <div className="flex items-center gap-2 py-4 text-[13px] text-dbx-text-secondary">
        <Loader2 size={14} className="animate-spin" /> Loading groups...
      </div>
    ) : (
      <div className="rounded border border-dbx-border overflow-hidden mb-4 text-[13px]">
        {groups.length === 0 ? (
          <div className="px-4 py-6 text-center text-dbx-text-secondary">
            No group role assignments. Add groups below.
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="bg-dbx-sidebar text-dbx-text-secondary text-[12px]">
                <th className="text-left px-3 py-2 font-medium">Group</th>
                <th className="text-left px-3 py-2 font-medium">Role</th>
                <th className="text-left px-3 py-2 font-medium">Granted by</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.group_name} className="border-t border-dbx-border">
                  <td className="px-3 py-2 text-dbx-text">{g.group_name}</td>
                  <td className="px-3 py-2 capitalize text-dbx-text">{g.role}</td>
                  <td className="px-3 py-2 text-dbx-text-secondary">{g.granted_by || '—'}</td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => handleRemoveGroup(g.group_name)}
                      className="text-dbx-text-secondary hover:text-red-600 transition-colors p-1" title="Remove group role">
                      <Trash2 size={13} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    )}

    {/* Add group */}
    <div className="flex items-center gap-2">
      <div className="relative flex-1" style={{ maxWidth: '260px' }}>
        <input type="text" placeholder="Group name"
          value={newGroupName}
          onChange={(e) => { setNewGroupName(e.target.value); setShowGroupDropdown(true) }}
          onFocus={() => setShowGroupDropdown(true)}
          onBlur={() => setTimeout(() => setShowGroupDropdown(false), 150)}
          onKeyDown={(e) => e.key === 'Enter' && handleAddGroup()}
          className={`${inputClass} w-full`}
        />
        {showGroupDropdown && workspaceGroups.length > 0 && (
          <GroupSearchDropdown
            query={newGroupName}
            groups={workspaceGroups}
            onSelect={(name) => { setNewGroupName(name); setShowGroupDropdown(false) }}
          />
        )}
      </div>
      <select value={newGroupRole} onChange={(e) => setNewGroupRole(e.target.value)}
        className={`${inputClass} bg-dbx-bg`} style={{ width: '110px' }}>
        <option value="use">Use</option>
        <option value="manage">Manage</option>
        {isOwner && <option value="owner">Owner</option>}
      </select>
      <button onClick={handleAddGroup} disabled={groupSaving || !newGroupName.trim()}
        className="h-8 px-4 text-[13px] rounded bg-dbx-blue text-white hover:bg-dbx-blue-hover disabled:opacity-50 transition-colors">
        {groupSaving ? 'Adding...' : 'Add'}
      </button>
    </div>
  </div>
)}
```

- [ ] **Step 6: Add GroupSearchDropdown component**

Before the main component, add (mirrors `UserSearchDropdown`):

```jsx
function GroupSearchDropdown({ query, groups, onSelect }) {
  const filtered = groups.filter(g =>
    g.displayName.toLowerCase().includes((query || '').toLowerCase())
  ).slice(0, 8)
  if (filtered.length === 0) return null
  return (
    <div className="absolute top-full left-0 right-0 mt-1 bg-dbx-bg border border-dbx-border rounded shadow-lg z-50 max-h-48 overflow-y-auto">
      {filtered.map(g => (
        <button key={g.displayName}
          onMouseDown={() => onSelect(g.displayName)}
          className="w-full text-left px-3 py-2 text-[13px] hover:bg-dbx-neutral-hover transition-colors flex justify-between items-center">
          <span className="text-dbx-text">{g.displayName}</span>
          <span className="text-[11px] text-dbx-text-secondary">{g.memberCount} members</span>
        </button>
      ))}
    </div>
  )
}
```

- [ ] **Step 7: Commit**

```
git add frontend/src/services/api.js frontend/src/components/settings/SettingsPage.jsx
git commit -m "feat(rbac): groups UI with autocomplete, workspace group discovery"
```

---

### Task 5: Build, deploy, verify

- [ ] **Step 1: Build frontend**
```bash
cd frontend && npm run build
```

- [ ] **Step 2: Upload dist + backend, deploy**
```bash
databricks workspace import-dir frontend/dist /Workspace/Users/lucas.rampimdesouza@databricks.com/genie-cache-queue/frontend/dist --profile AZURE --overwrite
databricks workspace import-dir backend/app /Workspace/Users/lucas.rampimdesouza@databricks.com/genie-cache-queue/backend/app --profile AZURE --overwrite
databricks apps deploy genie-cache-queue --source-code-path /Workspace/Users/lucas.rampimdesouza@databricks.com/genie-cache-queue --profile AZURE
```

- [ ] **Step 3: Verify in logs**
```bash
databricks apps logs genie-cache-queue --profile AZURE | grep -i "group_roles\|user_roles"
```
Expected: both tables initialized.

- [ ] **Step 4: Verify in UI**
- Hard refresh browser
- Navigate to Settings → Access Control → Groups
- Confirm workspace groups load in dropdown
- Assign a group role
- Verify user autocomplete also works in Users tab
