# Review: toolbox 0.4.0 (Arbeitsstand inkl. uncommitteter Änderungen)

Stand: 2026-10-27. Geprüft: `toolbox/`, `tests/`, `examples/`, `experiments/`,
README/CONTRIBUTING. Tests: 90 grün, ruff sauber, Coverage 96 %.

Alle als **bestätigt** markierten Punkte habe ich mit einem kleinen Skript
nachgestellt. Die Ausgabe steht jeweils dabei.

Breaking Changes sind erlaubt. Erledigte oder entfallene Punkte werden
gel?scht; verbleibende IDs bleiben stabil.

## 1. Dinge, die in der Praxis schieflaufen können

### R5 – `CallLoggingMiddleware` loggt rohe Argumente auf INFO

`middleware.py:54` loggt `call.raw_args` vollständig. Tool-Argumente
enthalten oft personenbezogene Daten oder Secrets (E-Mails, Tokens, Freitext).
Besser: DEBUG-Level oder ein `redact=`-Parameter.

### R6 – Uneinheitliche Behandlung unbekannter Argumente

Bei aus der Signatur erzeugten Models gilt `extra="forbid"`, bei
nutzerdefinierten Pydantic-Models der Pydantic-Default `ignore` (bestätigt).
Ein halluziniertes Argument führt also je nach Definitionsart zu einem
Fehler oder wird still verworfen. Das sollte einheitlich sein (ich würde
`forbid` nehmen) oder zumindest dokumentiert werden.

### R8 – Typ-Introspektion bei jedem Aufruf

`resolve_arguments` und `_tool_arguments` untersuchen bei jedem Aufruf erneut
Typannotationen und Signaturen (`arguments.py:18,20,50,52`). Der Teil für
Injection entfällt mit dem DI-System. Für explizite Params-Models bleibt
aber die Suche nach dem empfangenden Methodenparameter relevant.

**Vorschlag:** Die Zuordnung validierter Parameter zur gebundenen Methode
einmal bei der Registrierung ermitteln und wiederverwenden. Nicht auflösbare
Annotationen und mehrdeutige Params-Zuordnungen sollten dabei früh auffallen.

### R9 – `OutputBudget` begrenzt die Gesamtlänge nicht

Bei 60 + 40 Zeilen mit je 2000 Zeichen kommen bis zu 200 000 Zeichen durch,
grob 50 000 Tokens. Das ist kein echtes Budget. Weitere Kleinigkeiten:
`splitlines()` normalisiert `\r\n` und entfernt den abschließenden
Zeilenumbruch. Ein Marker für genau eine Zeile („1 lines omitted“) kostet so
viel wie die Zeile selbst. Vorschlag: zusätzlich `max_chars` einführen und
nur kürzen, wenn mindestens zwei Zeilen wegfallen.

---

## 2. Ergonomie und API-Design

### E5 – Die Ergebnis-Serialisierung baut jede App selbst

Laut README gehört das zum Adapter der App. In der Praxis schreibt aber jede
App das gleiche `_json_default`. `experiments/agent.py` macht es sogar falsch:
`json.dumps("text")` packt String-Ergebnisse noch einmal in Anführungszeichen,
das Modell sieht `"\"Tool failed: …\""`. Ein kleiner Helfer würde das lösen:
`to_text(result)` (str bleibt unverändert, BaseModel → JSON, sonst
`json.dumps(default=…)`).

### E6 – Approval

`requires_approval` ist ein statisches Bool und wird nicht durchgesetzt. Die
Middleware-Kette wäre der richtige Ort dafür:

```python
ApprovalMiddleware(confirm=async_confirm)       # gibt standardisierten Decline zurück
@tool(..., requires_approval=lambda p: p.amount > 100)  # abhängig von den Argumenten
```

Dann muss nicht jede App den Check vor `execute` nachbauen.

### E8 ? Dynamische Beschreibungen ? offen

Sollen Beschreibungen dynamisch aus dem Zustand einer Toolset-Instanz
entstehen k?nnen? Falls ja, sollte der Callback wie bei `available_when`
die Toolset-Instanz erhalten.

### E9 – Middleware

- `ToolMiddleware` ist eine Basisklasse, deren `__call__`
  `NotImplementedError` wirft. Ein `Protocol` (oder einfach ein Callable-Typ)
  würde auch schlichte `async def`-Middlewares erlauben.
- Der Parameter `next` überdeckt das gleichnamige Builtin. `call_next` ist
  üblich (Starlette, FastAPI).
- Um Argumente zu ändern, braucht man `dataclasses.replace(call, raw_args=…)`.
  Das sollte dokumentiert oder als `call.with_args(...)` angeboten werden.

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

## 3. Sprache und Benennung

| Konzept | Aktuelle Namen | Vorschlag |
|---|---|---|
| Params-Model | Decorator `params=`, `Tool(param_model=)`, `tool.input_model`, `build_schema(param_model=)` | einheitlich `params_model` bzw. `params=` |
| JSON-Schema | `tool.parameters`, `ToolSchema.parameters`, Anthropic `input_schema` | `tool.input_schema` (passt zu Anthropic/MCP) |
| Argumente | `ToolCall.raw_args`, `execute(arguments=)` | überall `arguments` |
| Zusatzdaten | Decorator `metadata=`, Attribut `tool.extra`, Klasse `ToolMetadata` (enthält tags/extra) | Decorator `extra=` **oder** Attribut `tool.metadata`, aber nicht beides |
| Kürzen | `OutputBudget.shape()` | `apply()` / `truncate()` / `__call__` |

Weitere Kleinigkeiten:

- `Toolbox.execute` meldet bei einem Tool, das es gibt, das aber nicht
  verfügbar ist, „Unknown tool“. Für das LLM ist das in Ordnung, beim Debuggen
  irritiert es. Ein Log-Eintrag auf DEBUG-Level mit dem echten Grund würde
  helfen.
- Die Model-Namen entstehen per `function_name.title()`, aus `get_HTTP` wird
  `Get_Http` → `GetHttpParams`. Rein kosmetisch, landet aber im Schema-`title`.

---

## 4. Doku und Repo

- 0.4.0 entfernt viele öffentliche APIs, aber es gibt weder CHANGELOG noch
  Migrationshinweise. Bei einer 0.x-Version ist das erlaubt, für Nutzer ist es
  trotzdem ein harter Bruch.
- `Agents.md` und `Claude.md` enthalten fast dieselben Konventionen. Eine
  Quelle reicht, die andere kann darauf verweisen.
- `pyproject.toml`: Classifiers (inkl. `Typing :: Typed`) und
  `[project.urls]` fehlen.
- `Tool.__eq__`/`__hash__` vergleichen nur über den Namen. Zwei
  verschiedene Tools aus zwei Registries gelten damit als gleich. Das ist
  vertretbar, sollte aber bewusst so entschieden sein.
