# Offene Review-Punkte: toolbx 0.4.0

Stand: 2026-10-27. Hier stehen nur noch offene API- und Dokumentationsfragen.

Breaking Changes sind erlaubt. Erledigte oder entfallene Punkte werden
gelöscht; verbleibende IDs bleiben stabil.

## 1. Ergonomie und API-Design

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
