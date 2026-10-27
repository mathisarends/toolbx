# Review: agenttoolkit 0.4.0 (Arbeitsstand inkl. uncommitteter Änderungen)

Stand: 2026-10-27. Geprüft: `agenttoolkit/`, `tests/`, `examples/`, `experiments/`,
README/CONTRIBUTING. Tests: 90 grün, ruff sauber, Coverage 96 %.

Alle als **bestätigt** markierten Punkte habe ich mit einem kleinen Skript
nachgestellt. Die Ausgabe steht jeweils dabei.

---

## TL;DR

Der Kern ist schlank, gut getestet und hat einen klaren Scope (kein Agent-Loop,
keine Provider-Abhängigkeit). Atomare Registrierung, frühe Fehler bei der
Klassendefinition und die Toolset-Namespaces sind gut gelöst.

Die größten Baustellen:

1. **Zwei Dependency-Systeme, die sich widersprechen.** Der Container und der
   `ToolContext` werden von `Inject`, `provided()`/`requires()` und
   `description_from_context` jeweils unterschiedlich ausgewertet. Daraus
   entstehen echte Bugs (B2, B3).
2. **Fehler sind von Erfolgen nicht zu unterscheiden.** Die ErrorBoundary
   liefert Fehler als normalen String zurück (R4).
3. **Begriffe sind uneinheitlich.** plugin/toolset/namespace,
   params/param_model/input_model/parameters/raw_args/arguments/args,
   metadata/extra und vier Bedeutungen von „provide“.

---

## 1. Bugs

### B1 – entfällt

`status`/`format_status` wurde entfernt, weil Status-Texte Sache der UI sind.
Damit gibt es keinen Validierungsschritt mehr außerhalb der Middleware-Kette.

### B2 – `provided()` / `requires()` / `description_from_context` ignorieren den Container · hoch · bestätigt

`Inject[T]` sucht zuerst im Container und dann im Context
(`arguments.py:27-32`). Availability und dynamische Beschreibung schauen aber
nur in den `ToolContext` (`binding.py:20-22`, `51-68`). Ein Tool, das seine
Dependency aus dem Container bekommt und mit `provided(Client)` abgesichert
ist, wird deshalb nie angezeigt und kann nicht aufgerufen werden:

```
schema names: []
execute("use") -> LookupError: Unknown tool 'use'. Available: []
```

### B3 – Container hat Vorrang vor dem per-Call-Context · mittel · bestätigt

`execute(..., context=ToolContext(Client("from-context")))` injiziert trotzdem
den Container-Singleton (`arguments.py:27`). Ein expliziter Wert pro Aufruf
sollte gewinnen. Sonst lassen sich Dependencies weder in Tests noch pro
Mandant oder Request überschreiben.

**Fix für B2 und B3:** eine einzige Auflösefunktion mit fester Reihenfolge
(per-Call-Context → Registry-Context → Container), die von `Inject`,
Availability und Description gemeinsam genutzt wird. Weil der Container async
ist und Availability sync, sollte Availability beim Container nur `has()`
prüfen.

### B4 – Abbruch während der Dependency-Erzeugung trifft auch fremde Calls · mittel · bestätigt

`DependencyContainer._resolve` (`dependency.py:50-76`) setzt eine
`CancelledError` des ersten Aufrufers in das gemeinsame Future. Ein zweiter,
paralleler Tool-Call, der auf dieselbe Dependency wartet, bekommt dann
ebenfalls `CancelledError`, obwohl er nie abgebrochen wurde. Typischer
Auslöser ist eine Timeout-Middleware auf Call A, die Call B mitreißt.
`ErrorBoundaryMiddleware` fängt nur `Exception`, der Fehler läuft also bis
ganz nach oben durch.

```
task (cancelled): CancelledError
waiter (nicht cancelled): CancelledError
```

**Fix:** Die Factory in einem eigenen Task starten und Wartende mit
`asyncio.shield` warten lassen. Alternativ bei Abbruch das Pending-Future
verwerfen, ohne eine Exception hineinzuschreiben, und Wartende neu auflösen
lassen.

### B5 – Exportierte Schemas sind Referenzen auf den internen Tool-Zustand · mittel · bestätigt

`Tool.to_schema` übergibt `self.parameters` direkt (`models.py:93-97`).
Pydantic kopiert dabei nur flach, und `to_anthropic_schema` gibt das Dict
unverändert zurück (`schema.py:21-26`). Wer das Schema nachbearbeitet
(OpenAI-strict-Transform, `cache_control`, Beschreibungen kürzen), verändert
dabei dauerhaft das Tool:

```
tool.parameters["properties"]["q"] == {..., "INJECTED": True, "NATIVE": True}
```

**Fix:** In `to_schema` mit `deepcopy` arbeiten, oder das Schema intern
eingefroren halten.

### B6 – `merge()` ist nicht atomar · mittel · bestätigt

`merge` registriert die Tools einzeln (`registry.py:201-203`). Bei einer
Kollision mitten in der Schleife bleibt die Registry halb gemerged:

```
merge raised "Tool 'x' already registered"; a2 now: ['x', 'y']
```

Das widerspricht dem Versprechen aus dem README: „Registration is atomic“.
Kollisionen sollten vorab gesammelt werden, so wie `add()` es schon macht.

### B7 – Tool-Namen von Funktions-Tools werden nicht validiert · mittel · bestätigt

`Tool.__init__` prüft nur, ob der Name leer ist (`models.py:54`). Namen wie
`"my tool!"` oder 100 Zeichen lange Namen gehen durch und scheitern erst beim
Provider (OpenAI/Anthropic erlauben `^[a-zA-Z0-9_-]{1,64}$`). Auch
`require_valid_name` (`toolset.py:21`) prüft keine Länge, und
`namespace + "_" + local_name` kann über 64 Zeichen kommen.

**Fix:** Eine gemeinsame Namensprüfung in `Tool.__init__` einbauen,
einschließlich Längenlimit.

### B8 – Parameter namens `self`/`cls` verschwinden aus dem Schema · niedrig · bestätigt

`schema.py:85`, `schema.py:127` und `arguments.py:53` überspringen Parameter
anhand ihres Namens. Eine Funktion `def classify(cls: str, text: str)` ist
dadurch nicht aufrufbar: `cls` fehlt im Schema, und `extra="forbid"` lehnt
es ab.

Das Überspringen ist ohnehin unnötig, weil Toolset-Methoden gebunden
registriert werden und `inspect.signature` bei gebundenen Methoden `self`
schon weglässt. Die Sonderbehandlung kann ersatzlos entfallen.

### B9 – `Tool.parse_arguments` und `Tool.execute` passen nicht zusammen · mittel · bestätigt

`parse_arguments` liefert `model_dump(...)`, also Dicts. `execute` ruft die
rohe Funktion mit `**arguments` auf. Bei Tools mit Params-Model kommt dabei
heraus:

```
TypeError: search() got an unexpected keyword argument 'q'
```

Bei verschachtelten Models bekommt die Funktion außerdem Dicts statt
Model-Instanzen. Dazu kommt: `Tool.execute` umgeht Validierung, Injection und
Middleware, heißt aber genauso wie `Toolbox.execute`. Das ist eine Falle.

**Fix:** `parse_arguments` und `Tool.execute` entfernen oder privat machen
(`parse_arguments` wird nirgends genutzt). Alternativ `Tool.execute` zu
`invoke_raw` umbenennen.

### B10 – Falsche Overloads bei `get_schema` · mittel

`toolbox.py:12-18`: Der erste Overload nimmt **jeden** `ToolSchemaFormat` an und
verspricht `list[ToolSchema]`. `get_schema(ToolSchemaFormat.OPENAI)` liefert
aber Dicts. Der Typechecker meldet dann bei korrektem Code Fehler und
übersieht falschen Code. Außerdem wird `"OpenAI"` mit `ValueError` abgelehnt,
weil Groß- und Kleinschreibung zählt.

**Fix:** Overloads mit `Literal[ToolSchemaFormat.OPENAI, "openai"]` usw.
schreiben, oder besser getrennte Methoden anbieten (siehe E3).

### B11 – `Inject[Protocol]` / `Inject[list[str]]` scheitern erst beim Aufruf · mittel · bestätigt

`ToolContext.resolve` arbeitet mit `isinstance`. Bei nicht
`@runtime_checkable`-Protocols und generischen Aliasen gibt das einen
`TypeError` mitten in der Ausführung. Der Container sucht nur nach exakten
Typen, Interface-Bindings (`Inject[SearchPort]` mit `SearchClient` als
Provider) gehen also nicht. Gerade Ports/Protocols sind aber der natürliche
Anwendungsfall für DI.

**Fix:** Bei der Registrierung prüfen, ob der Inject-Typ mit `isinstance`
geprüft werden kann. Im Container explizite Bindings erlauben,
z. B. `@provide(as_=SearchPort)`.

### B12 – erledigt

`agenttoolkit/py.typed` ist angelegt und landet im Wheel.

### B13 – erledigt

`fail_under = 90` steht jetzt in `[tool.coverage.report]`.

### B14 – Leere Fehlermeldungen bei Exceptions ohne Text · niedrig · bestätigt

`ErrorBoundaryMiddleware` baut die Meldung aus `f"Tool failed: {error}"`. Bei
`TimeoutError()`, `KeyError` u. a. sieht das LLM dann nur `'Tool failed: '`
bzw. `Tool failed: 'x'`. Besser ist ein Fallback auf den Typnamen:
`str(error) or type(error).__name__`.

### B15 – `@provide` auf einer staticmethod wird still ignoriert · niedrig · bestätigt

`inspect.getmembers(..., predicate=inspect.ismethod)` (`dependency.py:94`)
findet keine staticmethods. Der Provider verschwindet ohne Fehlermeldung
(`has(A) == False`), und der spätere Fehler „Missing dependency“ führt in
die falsche Richtung. Entweder unterstützen oder klar ablehnen.

### B16 – `Inject` in Toolset-Methoden fällt erst bei `add()` auf · niedrig · bestätigt

Laut README fallen Fehler schon bei der Klassendefinition auf.
`_reject_plugin_method_injection` läuft aber erst in `ToolRegistry.add`. Auch
Schemafehler (variadische Parameter) zeigen sich erst bei `add()`.

**Fix:** Diese Prüfungen nach `collect_tool_entries` verschieben.

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

### R3 – `ToolContext` ist veränderbar und wird geteilt

- `provide()`, `clear()` und `without()` ändern den Context **in place**
  (`context.py:26-38`). `without` klingt nach einer Kopie, ist aber keine.
- Ein Context, der über `Toolbox(context=...)` oder `set_context` an eine
  geteilte Registry gehängt wird, ist globaler Zustand. Ein `provide(user)`
  in Request A ist auch in Request B sichtbar.
- `__len__` macht einen leeren Context falsy (`bool(ToolContext()) is False`,
  bestätigt). Ein Ausdruck wie `context or default_context` wechselt dann
  still auf den Default.

**Vorschlag:** Den Context unveränderlich machen und Methoden wie
`with_(*deps) -> ToolContext` anbieten. `__len__` entfernen oder `__bool__`
explizit auf `True` setzen.

### R4 – Erfolg und Fehler sind im Ergebnis nicht unterscheidbar

`ErrorBoundaryMiddleware` gibt einen `str` zurück. Der Loop kann einen
Fehler nicht von einem Tool unterscheiden, das selbst einen String liefert.
Anthropic (`is_error: true`) und andere Provider haben dafür ein eigenes
Feld. `experiments/agent.py:96` muss das Format sogar nachbauen
(`"Tool failed: Declined by user"`).

Außerdem landet der rohe Exception-Text beim LLM: Connection-Strings,
Pfade, interne IDs und die mehrzeilige Pydantic-Fehlermeldung samt Klassennamen
wie `SParams`.

**Vorschlag:** Einen kleinen Ergebnistyp oder eine `ToolError`-Exception
einführen, plus einen `formatter=`-Hook an der ErrorBoundary:

```python
ErrorBoundaryMiddleware(format=lambda error: ...)  # was das Modell sieht
result = await toolbox.execute(...)                   # -> ToolOutcome(value, is_error)
```

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

### R7 – `parameters=` kann von der Validierung abweichen

`Tool(parameters=...)` überschreibt das Schema, validiert wird aber weiter
gegen `input_model`. Das Modell sieht dann ein anderes Schema, als tatsächlich
geprüft wird. Entweder eine Warnung ausgeben oder dokumentieren, dass
`parameters` nur kosmetisch ist.

### R8 – Typ-Introspektion bei jedem Aufruf

Bei jedem `execute` laufen `get_type_hints` und `inspect.signature` doppelt
(`arguments.py:18,20,50,52`). Das kostet Zeit, und Fehler wie
nicht-auflösbare Annotationen oder nicht prüfbare Protocols tauchen erst zur
Laufzeit auf. Besser: den Injection-Plan einmal in `Tool.__init__` berechnen
(`[(name, type, has_default)]`) und `_is_injected` nicht in drei Modulen
(`schema.py`, `arguments.py`, `registry.py`) duplizieren.

### R9 – `OutputBudget` begrenzt die Gesamtlänge nicht

Bei 60 + 40 Zeilen mit je 2000 Zeichen kommen bis zu 200 000 Zeichen durch,
grob 50 000 Tokens. Das ist kein echtes Budget. Weitere Kleinigkeiten:
`splitlines()` normalisiert `\r\n` und entfernt den abschließenden
Zeilenumbruch. Ein Marker für genau eine Zeile („1 lines omitted“) kostet so
viel wie die Zeile selbst. Vorschlag: zusätzlich `max_chars` einführen und
nur kürzen, wenn mindestens zwei Zeilen wegfallen.

---

## 3. Ergonomie und API-Design

### E1 – Ein Decorator für alles

Derzeit gibt es `@toolbox.tool(...)` (an eine Registry gebunden) und `@tool(...)`
(nur eine Markierung, nur für Methoden). Dadurch braucht man ein globales
`toolbox = Toolbox()` auf Modulebene, und Funktions-Tools lassen sich nicht ohne
Registry definieren, wiederverwenden oder isoliert testen.

**Vorschlag:** `@tool` funktioniert auch für freie Funktionen, und
Registrierung passiert nur bei der Komposition:

```python
@tool("Add two integers.")
def add(a: int, b: int) -> int: ...

toolbox = Toolbox(add, CatalogTools(catalog), middleware=[...])
```

`@toolbox.tool` kann als Abkürzung bleiben.

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
toolbox.to_openai(context=...)  # list[dict]
toolbox.to_anthropic(context=...)
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

### E7 – Viel Boilerplate, um eine vorhandene Instanz zu injizieren

Für „ich habe schon ein `db`“ braucht man laut README eine Provider-Klasse mit
`__init__` und einer `@provide`-Methode. Einfacher wäre:

```python
Toolbox(dependencies=[db, search_client])          # Instanzen, Typ = type(obj)
Toolbox(dependencies={SearchPort: search_client})  # explizites Binding
```

Daneben fehlt das Request-Scope: Für pro-Request-Werte gibt es nur den
`ToolContext`, der aber anders auflöst (isinstance, der zuletzt
hinzugefügte gewinnt) als der Container (exakter Typ, Singleton). Zwei
Mechanismen mit unterschiedlicher Semantik für dasselbe Ziel sind schwer zu
vermitteln (siehe B2/B3).

### E8 – Availability und Description

- Bei `requires(X, predicate=...)` ist das Prädikat Pflicht, und `provided(X)`
  existiert nur als Variante ohne Prädikat. Besser wäre eine Funktion
  `requires(X)` mit optionalem `where=`.
- `description_from_context` unterstützt genau eine Dependency.
  `ToolAvailability` nimmt dagegen beliebige Callables. Symmetrischer wäre
  `description=lambda ctx: ...`.
- Der Parameter `available_when` und die Funktion `description_from_context`
  folgen unterschiedlichen Namensmustern.

### E9 – Middleware

- `ToolMiddleware` ist eine Basisklasse, deren `__call__`
  `NotImplementedError` wirft. Ein `Protocol` (oder einfach ein Callable-Typ)
  würde auch schlichte `async def`-Middlewares erlauben.
- Der Parameter `next` überdeckt das gleichnamige Builtin. `call_next` ist
  üblich (Starlette, FastAPI).
- `ToolHandler` wird nicht exportiert. `examples/custom_middleware.py`
  importiert es aus dem internen Modul `agenttoolkit.tools.middleware`.
- Um Argumente zu ändern, braucht man `dataclasses.replace(call, raw_args=…)`.
  Das sollte dokumentiert oder als `call.with_args(...)` angeboten werden.

### E10 – Registry-Grundfunktionen fehlen

`get()` liefert `None`, deshalb gibt es überall `if tool is not None`. Es
fehlen `__getitem__`, `__contains__`, `names`, `remove`/`unregister` und eine
Teilmenge oder Ansicht (`toolbox.subset(tags=…)`), z. B. für Sub-Agenten.

### E11 – Dekorator-Signatur

- `name` ist der zweite **positionale** Parameter:
  `@toolbox.tool("desc", "name")` liest sich schlecht. Er sollte nur als Keyword
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
| Gruppe von Methoden-Tools | `Toolset`, „plugin“ (`plugins.py`, `plugin_name`, `add_plugin(name=)`, „Plugin tool … must be …“, „Plugin 'x' is already registered“, `_reject_plugin_method_injection`) | durchgehend **toolset** + **namespace**; `add_plugin` entfernen, `Tool.plugin_name` → `Tool.namespace`, `plugins.py` → `decorators.py` |
| Params-Model | Decorator `params=`, `Tool(param_model=)`, `tool.input_model`, `build_schema(param_model=)` | einheitlich `params_model` bzw. `params=` |
| JSON-Schema | `tool.parameters`, `ToolSchema.parameters`, Anthropic `input_schema` | `tool.input_schema` (passt zu Anthropic/MCP) |
| Argumente | `ToolCall.raw_args`, `execute(arguments=)` | überall `arguments` |
| Zusatzdaten | Decorator `metadata=`, Attribut `tool.extra`, Klasse `ToolMetadata` (enthält tags/extra) | Decorator `extra=` **oder** Attribut `tool.metadata`, aber nicht beides |
| „provide“ | `@provide` (Factory), `DependencyProvider` (Klasse), `ToolContext.provide()` (Werte hinzufügen), `provided()` (Availability) | vier Bedeutungen für ein Wort. Vorschlag: `@provides`, `ToolContext.with_()`, `requires()` |
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

## 5. Fehlende Features (nach Wichtigkeit)

1. Ergebnistyp mit `is_error` und ein Formatter-Hook für Fehler (R4)
2. Eine einzige Dependency-Auflösung mit Vorrang des per-Call-Context
   (B2/B3/E7)
3. `@tool` auch für freie Funktionen (E1)
4. Tool-Call-ID und JSON-String als Eingabe in `execute`/`ToolCall` (E4)
5. Sync-Tools in einem Thread ausführen (R2)
6. `ApprovalMiddleware` und Approval abhängig von den Argumenten (E6)
7. Docstring als Fallback für Beschreibungen (E11)
8. Filtern und Teilmengen nach Tags, Registry-Grundfunktionen (E3/E10)
9. Schema-Normalizer und OpenAI-strict-Export (E12)
10. Helfer zur Serialisierung der Ergebnisse (E5)
11. `OutputBudget` mit Gesamtgrenze und optional als Middleware (R9)

---

## 6. Doku und Repo

- 0.4.0 entfernt viele öffentliche APIs, aber es gibt weder CHANGELOG noch
  Migrationshinweise. Bei einer 0.x-Version ist das erlaubt, für Nutzer ist es
  trotzdem ein harter Bruch.
- `DependencyContainer` ist nicht exportiert, obwohl `Toolbox(container=...)`
  öffentlich ist. Dasselbe gilt für `ToolHandler` (siehe E9).
- `Agents.md` und `Claude.md` enthalten fast dieselben Konventionen. Eine
  Quelle reicht, die andere kann darauf verweisen.
- `pyproject.toml`: Classifiers (inkl. `Typing :: Typed`) und
  `[project.urls]` fehlen.
- `Tool.__eq__`/`__hash__` vergleichen nur über den Namen. Zwei
  verschiedene Tools aus zwei Registries gelten damit als gleich. Das ist
  vertretbar, sollte aber bewusst so entschieden sein.

---

## 7. Empfohlene Reihenfolge

**Schnell erledigt (je unter einer Stunde):**
B5 · B6 · B8 · B14 · B15 · `name` nur als Keyword (E11)

**Kurzfristig (nächster Minor):**
B2 + B3 (eine Auflösefunktion) · B4 · B7 · B9 · B10/E3 · B16/B17/R8
(Injection-Plan bei der Registrierung) · Begriffe vereinheitlichen
(Abschnitt 4, vor allem plugin → toolset)

**Mittelfristig (API-Entscheidungen):**
R1 (Flatten explizit machen) · R3 (unveränderlicher Context) · R4/E5
(Ergebnistyp) · E1 (ein Decorator) · E2 (`Toolbox` zusammenführen) · E6
(Approval-Middleware) · R2 (Sync-Tools in Threads)
