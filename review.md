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

### E10 – Registry-Grundfunktionen fehlen

`get()` liefert `None`, deshalb gibt es überall `if tool is not None`. Es
fehlen `__getitem__`, `__contains__`, `names`, `remove`/`unregister` und eine
Teilmenge oder Ansicht (`toolbox.subset(tags=…)`), z. B. für Sub-Agenten.

### E11 – Dekorator-Signatur

- `name` ist der zweite **positionale** Parameter:
  `@tool("desc", "name")` liest sich schlecht. Er sollte nur als Keyword
  erlaubt sein.
- Fehlt die Beschreibung, wird sie still zu `""` (bestätigt). Die Docstring
  wird ignoriert. Erwartet wäre: Docstring als Fallback, idealerweise mit
  `Args:`-Abschnitt als Beschreibung der Felder. Oder zumindest eine Warnung,
  wenn die Beschreibung leer ist.

### E12 – Das Schema enthält viel Ballast

Pydantic erzeugt für jedes Feld `title` (`"title": "Q"`), dazu ein
Model-`title` (`"SParams"`) und bei verschachtelten Models
`$defs`/`$ref`. Das kostet Tokens, und einige Provider (Gemini,
OpenAI-strict) verarbeiten `$ref` schlecht oder gar nicht. Vorschlag: einen
optionalen Schema-Normalizer anbieten (Titles entfernen, `$ref` auflösen) und
einen `strict=True`-Export für OpenAI (`additionalProperties: false`, alle
Felder `required`, optionale Felder als nullable).

---

## 2. Sprache und Benennung

- `Toolbox.execute` meldet bei einem Tool, das es gibt, das aber nicht
  verfügbar ist, „Unknown tool“. Für das LLM ist das in Ordnung, beim Debuggen
  irritiert es. Ein Log-Eintrag auf DEBUG-Level mit dem echten Grund würde
  helfen.
- Die Model-Namen entstehen per `function_name.title()`, aus `get_HTTP` wird
  `Get_Http` → `GetHttpParams`. Rein kosmetisch, landet aber im Schema-`title`.

---

## 3. Doku und Repo

- `Agents.md` und `Claude.md` enthalten fast dieselben Konventionen. Eine
  Quelle reicht, die andere kann darauf verweisen.
- `pyproject.toml`: Classifiers (inkl. `Typing :: Typed`) und
  `[project.urls]` fehlen.
- `Tool.__eq__`/`__hash__` vergleichen nur über den Namen. Zwei
  verschiedene Tools aus zwei Registries gelten damit als gleich. Das ist
  vertretbar, sollte aber bewusst so entschieden sein.
