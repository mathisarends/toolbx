# Experiments

Run the chat entry point from the repository root:

```powershell
uv run python experiments\chat.py
```

- `agent.py` contains the shared agent loop.
- `chat.py` is the runnable composition.
- `model.py` wraps the chat model.
- `environments/` contains reusable user interfaces.
