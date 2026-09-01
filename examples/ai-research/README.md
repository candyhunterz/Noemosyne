# Illustrative AI-research seed

`seed.yaml` is a deterministic, redistributable annotation package. It stores source metadata and stable locators only—no paper PDFs or copyrighted excerpts. Original annotations in this directory are licensed under CC BY 4.0; third-party source metadata and linked artifacts retain their own terms.

Import it after migrations with:

```sh
uv run noemosyne-seed import examples/ai-research/seed.yaml
```

Running the same package version and hash again is a no-op. A changed payload with the same package ID and version is rejected.

Export the accepted, validated package envelope for a semantic round trip with:

```sh
uv run noemosyne-seed export noemosyne.ai-research.illustrative@1.0.0 exported-seed.yaml
```
