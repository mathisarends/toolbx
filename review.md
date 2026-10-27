# Offene Review-Punkte: toolbx 0.4.0

Stand: 2026-10-27. Hier stehen nur noch offene API- und Dokumentationsfragen.

Breaking Changes sind erlaubt. Erledigte oder entfallene Punkte werden
gelöscht; verbleibende IDs bleiben stabil.

## 1. Ergonomie und API-Design

### E6 – Approval

`requires_approval` ist ein statisches Bool und wird nicht durchgesetzt. Die
Middleware-Kette wäre der richtige Ort dafür:

```python
ApprovalMiddleware(confirm=async_confirm)       # gibt standardisierten Decline zurück
@tool(..., requires_approval=lambda p: p.amount > 100)  # abhängig von den Argumenten
```

Dann muss nicht jede App den Check vor `execute` nachbauen.

### E8 – Dynamische Beschreibungen · offen

Sollen Beschreibungen dynamisch aus dem Zustand einer Toolset-Instanz
entstehen können? Falls ja, sollte der Callback wie bei `available_when`
die Toolset-Instanz erhalten.

---

## 2. Doku und Repo

- `Agents.md` und `Claude.md` enthalten fast dieselben Konventionen. Eine
  Quelle reicht, die andere kann darauf verweisen.
- `pyproject.toml`: Classifiers (inkl. `Typing :: Typed`) und
  `[project.urls]` fehlen.
- `Tool.__eq__`/`__hash__` vergleichen nur über den Namen. Zwei
  verschiedene Tools aus zwei Registries gelten damit als gleich. Das ist
  vertretbar, sollte aber bewusst so entschieden sein.
