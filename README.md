# notion-sync

## Description

This action will sync your Notion page to your GitHub repository. It will scan your repository for all markdown files and check if their front-matter contains a `notion-url` field. If it does, it will update the file with the content from the Notion page. 

## Getting Started

1. Create [an integration and find the token](https://www.notion.so/my-integrations). [Learn more about authorization](https://developers.notion.com/docs/authorization).

2. Use the token to create a secret in your repository called `NOTION_TOKEN`.

3. Create a workflow file in your repository's `.github/workflows` directory. An example workflow is available below. For more information, reference the GitHub Help Documentation for [Creating a workflow file](https://help.github.com/en/articles/configuring-a-workflow#creating-a-workflow-file).

```yaml
name: sync-notion-to-github

on:
  schedule:
    - cron: '0 0 * * *' # every day at 00:00 UTC
  workflow_dispatch:
  push:
    branches:
      - main

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
    - name: notion-sync
      uses: YouXam/Notion-GitHub-Sync@v1
      with:
        notion_token: ${{ secrets.NOTION_TOKEN }}
```

Done! Now, every day at 00:00 UTC, your Notion page will be synced to your GitHub repository.

For example, if you have a file called `example.md` and it's content is:

```markdown
---
notion-url: https://www.notion.so/xxxx/xxxx
---
```

Then, when the workflow runs, the content of `example.md` will be replaced with the content of the Notion page at `https://www.notion.so/xxxx/xxxx`.

Note: All this Notion pages you use must be connected to your integration.
