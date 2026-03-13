# Deployment Guide

## Quick Deploy to Databricks Apps

### 1. Prerequisites
- Databricks workspace with Apps enabled
- Databricks CLI installed and configured
- Lakebase instance created (optional but recommended)

### 2. Sync Code to Workspace
```bash
databricks sync . /Workspace/Users/<your-email>/genie-cache-demo
```

### 3. Deploy App
```bash
databricks apps deploy genie-cache-demo \
  --source-code-path /Workspace/Users/<your-email>/genie-cache-demo
```

### 4. Get App URL
```bash
databricks apps get genie-cache-demo
```

Look for the `url` field in the output.

### 5. Configure in UI
Open the app URL and navigate to **Settings**:

**Required:**
- Genie Space ID
- SQL Warehouse ID  
- User PAT

**For Lakebase (Recommended):**
- Storage Backend: "Databricks Lakebase"
- Lakebase Instance Name
- Lakebase Catalog
- Lakebase Schema: `public`
- Cache Table Name: `cached_queries`
- Query Log Table Name: `query_logs`

Click **Save Configuration**.

### 6. Test
1. Go to Chat tab
2. Submit: "Show me sales data"
3. Check Query Logs to verify it processed
4. Submit the same query again → Should be faster (cache hit!)

## Continuous Deployment

For updates:
```bash
# Make code changes
# Then sync and redeploy
databricks sync . /Workspace/Users/<your-email>/genie-cache-demo
databricks apps deploy genie-cache-demo \
  --source-code-path /Workspace/Users/<your-email>/genie-cache-demo
```

## View Logs
```bash
databricks apps logs genie-cache-demo --follow
```

## Troubleshooting

### App Not Starting
Check deployment status:
```bash
databricks apps get genie-cache-demo
```

Look for `status.state` and `status.message`.

### Configuration Issues
All configuration is done through the UI Settings page. No environment variables needed!

### Database Tables Not Created
Tables are auto-created on first query submission. Ensure:
- Lakebase instance is running
- PAT has CREATE TABLE permissions
- Settings are saved correctly
