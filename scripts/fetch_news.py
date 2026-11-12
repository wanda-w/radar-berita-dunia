name: Update berita

# Hanya berjalan saat dipicu manual: tombol "Run workflow" di tab Actions,
# atau lewat prompt ke Claude (gh workflow run update.yml).
on:
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  update:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - id: pages
        uses: actions/configure-pages@v5

      - name: Ambil berita
        run: python scripts/fetch_news.py --out _site --prev-url "${{ steps.pages.outputs.base_url }}"

      - uses: actions/upload-pages-artifact@v3
        with:
          path: _site

      - id: deployment
        uses: actions/deploy-pages@v4
