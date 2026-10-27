# Review: toolbox 0.4.0 (Arbeitsstand inkl. uncommitteter Änderungen)

Stand: 2026-10-27. Geprüft: `toolbox/`, `tests/`, `examples/`, `experiments/`,
README/CONTRIBUTING. Tests: 90 grün, ruff sauber, Coverage 96 %.

Alle als **bestätigt** markierten Punkte habe ich mit einem kleinen Skript
nachgestellt. Die Ausgabe steht jeweils dabei.

## Festgelegte API-Richtung

- Vereinfachungen dürfen die bestehende API brechen; Kompatibilitäts-Aliasse
  sind dafür nicht erforderlich.
- Tools werden ausschließlich als mit `@tool` markierte Instanzmethoden von
  `Toolset`-Unterklassen definiert. Die `Toolbox` registriert deren Instanzen.
  Freie Funktions-Tools, `@toolbox.tool` und die öffentliche Registrierung
  beliebiger `Tool`-Objekte entfallen als alternative Definitionswege.
- Dependencies werden der Toolset-Instanz explizit über ihren Konstruktor
  übergeben. `Inject`, `DependencyContainer`, `DependencyProvider`, `@provide`
  und der typbasierte `ToolContext` entfallen als bibliothekseigenes DI-System.
- Parameter dürfen weiterhin aus der Methodensignatur oder einem expliziten
  Params-Modell (`params=Model`) entstehen. Das Flatten-Verhalten ist noch
  zu klären (R1).
- `Toolbox.execute` liefert normale Rückgabewerte und lässt Exceptions zum
  aufrufenden Agent-Loop durch. Fehlerbehandlung per Middleware ist optional
  und wird ausdrücklich eingebunden; ein einheitlicher `ToolOutcome`-Wrapper
  ist nicht vorgesehen.
- Dynamische Verfügbarkeit bleibt erhalten: Tools sollen sich ein- und
  ausschalten lassen. Die konkrete API sowie die weitere Unterstützung
  dynamischer Beschreibungen sind noch offen (E8).
- `ToolRegistry` geht in `Toolbox` auf. Schema-Export erfolgt über `schemas()`,
  `to_openai()` und `to_anthropic()` (E2/E3).
- `execute` soll Mappings und JSON-Strings sowie eine optionale Call-ID
  annehmen. Parallele Tool-Calls werden über `execute_many` unterstützt (E4).

Die Zielrichtung ist beschlossen, die Umsetzung steht noch aus. Erledigte
oder entfallene Punkte werden gelöscht; verbleibende IDs bleiben stabil.

---

## 1. Bugs

### B10 – Falsche Overloads bei `get_schema` · mittel

`toolbox.py:12-18`: Der erste Overload nimmt **jeden** `ToolSchemaFormat` an und
verspricht `list[ToolSchema]`. `get_schema(ToolSchemaFormat.OPENAI)` liefert
aber Dicts. Der Typechecker meldet dann bei korrektem Code Fehler und
übersieht falschen Code. Außerdem wird `"OpenAI"` mit `ValueError` abgelehnt,
weil Groß- und Kleinschreibung zählt.

**Fix:** Overloads mit `Literal[ToolSchemaFormat.OPENAI, "openai"]` usw.
schreiben, oder besser getrennte Methoden anbieten (siehe E3).

### B16 – Schemafehler in Toolset-Methoden fallen erst bei `add()` auf · niedrig · bestätigt

Laut README fallen Fehler schon bei der Klassendefinition auf.
Schemafehler wie variadische Parameter zeigen sich aber erst bei `add()`.

**Fix:** Die Signatur- und Schemaprüfung bereits bei der Klassendefinition
ausführen, etwa über `collect_tool_entries`.

### B17 – Parameter ohne Annotation werden still zu `str` · niedrig · bestätigt

`hints.get(name, str)` (`schema.py:87`): `def u(x)` erzeugt
`{"type": "string"}`, und `execute("u", {"x": 5})` scheitert. Besser ist
`Any` oder ein klarer Fehler bei der Registrierung.

---

## 2. Dinge, die in der Praxis schieflaufen können

### R1 – Implizites Flatten eines einzelnen Model-Parameters

`_infer_param_model` (`schema.py:51-74`) macht aus `def create_user(user: User)`
ein Schema mit den Feldern **von `User` auf oberster Ebene** (`{"name": …}`)
statt `{"user": {…}}`. Das ist überraschend. Noch schlimmer: Kommt später ein
zweiter Parameter hinzu, ändert sich die Schema-Form unbemerkt, und damit das
Prompt-Verhalten und gespeicherte Transkripte.

**Vorschlag:** Nur flatten, wenn es explizit gewünscht ist (`params=Model`),
oder mit einem klaren Marker wie `params: Params[SearchParams]`. Sonst
verhalten sich Model-Parameter wie alle anderen Parameter.

### R2 – Sync-Tools blockieren den Event-Loop

`Tool.execute` ruft Sync-Funktionen direkt im Loop auf. Ein `requests.get`
oder eine Datenbankabfrage in einem Sync-Tool blockiert alle parallelen
Tool-Calls und Streams. Vorschlag: `@tool(..., run_in_thread=True)` oder
standardmäßig `asyncio.to_thread` für Sync-Funktionen.

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

## 3. Ergonomie und API-Design

### E2 – `Toolbox` vs. `ToolRegistry`

Seit `StructuredOutputTools` entfernt ist, gibt es keinen zweiten Nutzer der
Basisklasse mehr. Die Aufteilung ist nur noch Ballast. Der Docstring
„Shared registration … for tool representations“ ist ein Überbleibsel.
Vorschlag: zu einer Klasse `Toolbox` zusammenführen.

### E3 – Schema-Export

`toolbox.get_schema(ToolSchemaFormat.ANTHROPIC)` ist lang, liefert eine Liste
unter einem Namen im Singular und hat die Typing-Probleme aus B10. Besser:

```python
toolbox.schemas()               # list[ToolSchema]
toolbox.to_openai()             # list[dict]
toolbox.to_anthropic()
```

Optional dazu Filter: `toolbox.schemas(tags={"read"})`, `include=`, `exclude=`.
Tags gibt es bereits, aber keine API wertet sie aus.

### E4 – `execute` passt nicht zu dem, was Provider liefern

- OpenAI liefert die Argumente als JSON-String. `execute` nimmt aber nur ein
  Mapping, jeder Loop macht also `json.loads(... or "{}")` selbst.
- Die Tool-Call-ID des Providers taucht nicht in `ToolCall` auf. Middleware
  für Tracing, Approval oder Caching kann Aufrufe deshalb nicht zuordnen.
- Es gibt keinen Helfer für parallele Tool-Calls (`execute_many` mit
  `gather` und einer Fehlerbehandlung pro Call).

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

### E8 – Availability und Description über die Toolset-Instanz · offen

Mit dem DI-System entfallen `provided()`, `requires()` und
`description_from_context`. Benötigte Werte liegen künftig explizit auf der
Toolset-Instanz.

Dynamische Verfügbarkeit bleibt erhalten; Tools sollen sich ein- und
ausschalten lassen.

**Noch zu entscheiden:** Erfolgt das Umschalten über eine explizite
Enable/Disable-API oder über Methoden bzw. Callbacks auf der Toolset-Instanz?
Wie wirkt sich der Zustand auf Schema-Export und direkte Aufrufe aus?
Dynamische Beschreibungen sind separat noch zu klären.

### E9 – Middleware

- `ToolMiddleware` ist eine Basisklasse, deren `__call__`
  `NotImplementedError` wirft. Ein `Protocol` (oder einfach ein Callable-Typ)
  würde auch schlichte `async def`-Middlewares erlauben.
- Der Parameter `next` überdeckt das gleichnamige Builtin. `call_next` ist
  üblich (Starlette, FastAPI).
- `ToolHandler` wird nicht exportiert. `examples/custom_middleware.py`
  importiert es aus dem internen Modul `toolbox.tools.middleware`.
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

## 4. Sprache und Benennung

| Konzept | Aktuelle Namen | Vorschlag |
|---|---|---|
| Gruppe von Methoden-Tools | `Toolset`, „plugin“ (`plugins.py`, `plugin_name`, `add_plugin(name=)`, „Plugin tool … must be …“, „Plugin 'x' is already registered“) | durchgehend **toolset** + **namespace**; `add_plugin` entfernen, `Tool.plugin_name` → `Tool.namespace`, `plugins.py` → `decorators.py` |
| Params-Model | Decorator `params=`, `Tool(param_model=)`, `tool.input_model`, `build_schema(param_model=)` | einheitlich `params_model` bzw. `params=` |
| JSON-Schema | `tool.parameters`, `ToolSchema.parameters`, Anthropic `input_schema` | `tool.input_schema` (passt zu Anthropic/MCP) |
| Argumente | `ToolCall.raw_args`, `execute(arguments=)` | überall `arguments` |
| Zusatzdaten | Decorator `metadata=`, Attribut `tool.extra`, Klasse `ToolMetadata` (enthält tags/extra) | Decorator `extra=` **oder** Attribut `tool.metadata`, aber nicht beides |
| Kürzen | `OutputBudget.shape()` | `apply()` / `truncate()` / `__call__` |
| Format-Enum | `ToolSchemaFormat.NATIVE` | wird mit E3 überflüssig |

Weitere Kleinigkeiten:

- `ToolRegistry.execute` meldet bei einem Tool, das es gibt, das aber nicht
  verfügbar ist, „Unknown tool“. Für das LLM ist das in Ordnung, beim Debuggen
  irritiert es. Ein Log-Eintrag auf DEBUG-Level mit dem echten Grund würde
  helfen.
- Die Model-Namen entstehen per `function_name.title()`, aus `get_HTTP` wird
  `Get_Http` → `GetHttpParams`. Rein kosmetisch, landet aber im Schema-`title`.

---

## 5. Doku und Repo

- 0.4.0 entfernt viele öffentliche APIs, aber es gibt weder CHANGELOG noch
  Migrationshinweise. Bei einer 0.x-Version ist das erlaubt, für Nutzer ist es
  trotzdem ein harter Bruch.
- `ToolHandler` wird nicht exportiert (siehe E9).
- `Agents.md` und `Claude.md` enthalten fast dieselben Konventionen. Eine
  Quelle reicht, die andere kann darauf verweisen.
- `pyproject.toml`: Classifiers (inkl. `Typing :: Typed`) und
  `[project.urls]` fehlen.
- `Tool.__eq__`/`__hash__` vergleichen nur über den Namen. Zwei
  verschiedene Tools aus zwei Registries gelten damit als gleich. Das ist
  vertretbar, sollte aber bewusst so entschieden sein.

---

## 6. Empfohlene Reihenfolge

**Zuerst: beschlossene Vereinfachung umsetzen:**
Nur Toolset-Instanzen registrieren; Funktions-Tools und das DI-System samt
Context- und Binding-Helfern entfernen. Beispiele, Tests und Dokumentation
auf die explizite Übergabe von Dependencies im Toolset-Konstruktor umstellen.
Die neue API für Availability und Description vorher klären (E8).

**Kleine, unabhängige Korrekturen:**
`name` nur als Keyword (E11)

**Weitere Vereinfachungen und Validierung:**
B10/E3 · B16/B17/R8
(Signaturprüfung und Argumentzuordnung bei Definition bzw. Registrierung) ·
E2 (`Toolbox` zusammenführen) · Begriffe vereinheitlichen
(Abschnitt 4, vor allem plugin → toolset)

**Noch offene API-Entscheidungen:**
R1 (Flatten-Verhalten) · E5 (Serialisierung) · E6
(Approval-Middleware) · R2 (Sync-Tools in Threads). Breaking Changes sind
zulässig; der Nutzen zusätzlicher Komfortfunktionen ist jeweils noch zu klären.
