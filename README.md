# adrpy-ai

Edição Python do AdrPlus (CLI de gestão de Architecture Decision
Records), migrada seguindo o harness em
`../adr-migration-harness/HARNESS-MIGRACAO-ADR-CSHARP-PYTHON.md`.

CLI pura, args-in/JSON-out, sem wizard — projetada para ser operada por
um agente de IA via shell.

## Desenvolvimento

```bash
pip install -e ".[dev]"
adrpy --help
pytest
```
