# Klassenbasierte Tool-Gruppen und Constructor Injection

## Einordnung

`agenttoolkit` sollte zwei gleichwertige Authoring-Stile anbieten:

1. eine kleine, direkte API für Skripte und wenige Tools,
2. eine klassenbasierte API für größere Anwendungen mit Services, Dependency
   Injection und fachlich gruppierten Tools.

Die zweite API ist nicht einfach „eine Klasse pro Tool“. Eine Klasse bildet
vielmehr eine benannte Gruppe zusammengehöriger Tools und ist der
modellseitige Presentation Layer vor vorhandenen Application Services.

```text
LLM
 │
 │ Tool-Schemas und Tool-Calls
 ▼
CatalogPlugin                 ← LLM Presentation Layer
 ├── search()
 ├── get_product()
 └── compare_products()
          │
          ▼
CatalogService               ← Application-/Domain-Service
          │
          ▼
SearchClient, Repository ... ← Infrastruktur
```

Das entspricht dem nützlichen Teil des Semantic-Kernel-Modells: Ein Plugin ist
eine Gruppe semantisch beschriebener Funktionen und kann seine langlebigen
Dependencies per Konstruktor erhalten. Microsoft beschreibt Plugins gerade
für Enterprise-Anwendungen als Kapselung vorhandener Services und APIs und den
Kernel als zentralen DI- und Plugin-Container. Siehe [Plugins in Semantic
Kernel](https://learn.microsoft.com/en-us/semantic-kernel/concepts/plugins/)
und [Understanding the
kernel](https://learn.microsoft.com/en-us/semantic-kernel/concepts/kernel).

Wir sollten dieses Modell jedoch an die bestehende Architektur des Repositories
anpassen, statt Semantic Kernel vollständig nachzubauen.

## Empfehlung zum Wording

### `Plugin` verwenden

`Plugin` passt fachlich, wenn der Begriff bei uns klar definiert wird:

> Ein Plugin ist eine benannte Sammlung von Tools, die ein bestehendes
> Service-API für ein LLM präsentiert.

Der Begriff transportiert drei wichtige Eigenschaften:

- Ein Plugin enthält mehrere zusammengehörige Operationen.
- Nur ausdrücklich markierte Methoden werden nach außen exponiert.
- Das Plugin ist eine Adapter-/Presentation-Schicht, nicht selbst der
  Dependency Container.

Mögliche Nachteile sind, dass „Plugin“ auch dynamisch installierbare Pakete,
MCP-Server oder ein allgemeines Extension-System bedeuten kann. Deshalb sollte
Version 1 ausdrücklich von **nativen Plugins** beziehungsweise Python-Objekten
sprechen. Später könnten OpenAPI- oder MCP-basierte Quellen denselben
Registry-Unterbau nutzen, ohne dass die erste API das bereits versprechen muss.

`ToolGroup` wäre die konservativere Alternative. Der Name ist eindeutiger,
wirkt aber rein organisatorisch und drückt die Rolle als LLM-Adapter vor
Application Services weniger gut aus. Für die hier angestrebte Enterprise-API
ist daher `Plugin` die stärkere Wahl.

### Kein `Kernel`

Ein eigenes `Kernel`-Objekt ist nicht nötig. Im aktuellen Repository übernimmt
`Tools` bereits die relevanten Aufgaben:

- Tool-Registrierung,
- Schema-Erzeugung,
- Dispatch und Middleware,
- Besitz oder Verwendung des `DependencyContainer`,
- `APP`-, `TURN`- und `CALL`-Lifecycle.

Ein zusätzlicher Kernel würde entweder nur `Tools` umbenennen oder einen zweiten
zentralen Container schaffen. Beides würde die API vergrößern, ohne eine neue
fachliche Fähigkeit hinzuzufügen. `Tools` wird deshalb zum Host für Funktionen
**und** Plugins erweitert.

## Ziel-API

### Quick-/Script-API bleibt unverändert

```python
tools = Tools(dependencies=[Dependencies()])


@tools.tool("Search the catalog")
async def search(
    query: str,
    service: Inject[CatalogService],
) -> list[Product]:
    return await service.search(query)
```

Das bleibt der kürzeste Weg für einzelne Funktionen.

### Enterprise-/Plugin-API

```python
from agenttoolkit import Inject, Tools, tool


class CatalogPlugin:
    def __init__(
        self,
        catalog: CatalogService,
        recommendations: RecommendationService,
    ) -> None:
        self._catalog = catalog
        self._recommendations = recommendations

    @tool("Search the product catalog")
    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[Product]:
        return await self._catalog.search(query, limit=limit)

    @tool("Get one product by its stable identifier")
    async def get_product(self, product_id: str) -> Product:
        return await self._catalog.get(product_id)

    @tool("Compare products for the current user")
    async def compare_products(
        self,
        product_ids: list[str],
        user: Inject[CurrentUser],
    ) -> Comparison:
        products = await self._catalog.get_many(product_ids)
        return await self._recommendations.compare(user, products)

    def _normalize_query(self, query: str) -> str:
        # Nicht dekoriert, daher niemals für das Modell sichtbar.
        return " ".join(query.split())


plugin = CatalogPlugin(catalog_service, recommendation_service)

tools = Tools()
tools.add_plugin(plugin, name="catalog")
```

Die Klasse benötigt keine Basisklasse. Sie bleibt ein normales Python-Objekt,
das direkt konstruiert und getestet werden kann. `@tool(...)` markiert Methoden
nur mit deklarativen Tool-Metadaten; die eigentliche Registrierung erfolgt
atomar durch `add_plugin`.

Die API liest sich damit bewusst zweistufig:

```python
@tools.tool(...)       # Funktion sofort in genau dieser Registry registrieren
@tool(...)             # Methode als potentielles Plugin-Tool markieren
tools.add_plugin(...)  # Plugin-Instanz und alle markierten Methoden registrieren
```

Der module-level Decorator `@tool` sollte dieselben Argumente wie
`@tools.tool` akzeptieren:

```python
@tool(
    "Issue a refund",
    name="refund",
    status=lambda params: f"Refunding order {params.order_id}...",
    requires_approval=True,
    available_when=requires(User, predicate=lambda user: user.is_admin),
    tags=["billing", "write"],
    metadata={"owner": "billing-team"},
)
async def refund(self, params: RefundParams) -> Refund: ...
```

Dadurch gibt es nur eine Metadaten-Sprache. Der Unterschied liegt allein im
Registrierungszeitpunkt.

## Was `@tool` tun soll

Der Decorator registriert nichts und kennt keine `Tools`-Instanz. Er hängt nur
unveränderliche Definitionsmetadaten an die Funktion und gibt die ursprüngliche
Funktion zurück.

Konzeptionell:

```python
def tool(description, name=None, **options):
    def decorate(method):
        method.__tool_definition__ = ToolDefinition(
            description=description,
            name=name or method.__name__,
            **options,
        )
        return method

    return decorate
```

`tools.add_plugin(instance, name="catalog")` inspiziert anschließend die
gebundenen Methoden der Instanz, erzeugt für jede markierte Methode den bereits
vorhandenen `Tool`-Descriptor und registriert alle Descriptoren in derselben
Registry.

Nicht dekorierte öffentliche Methoden, Properties und `__call__` werden niemals
automatisch exponiert. Explizite Freigabe ist hier wichtiger als Reflection-
Convenience.

## Plugin- und Tool-Namen

Ein Plugin braucht einen stabilen Namen:

```python
tools.add_plugin(CatalogPlugin(...), name="catalog")
```

Der Name sollte nicht automatisch aus `CatalogPlugin.__name__` abgeleitet
werden. Python-Refactorings dürfen das modellseitige API nicht unbemerkt
ändern.

Provider stellen Tools in der Regel in einem flachen Namespace dar. Deshalb
sollten die tatsächlich exponierten Namen in Version 1 deterministisch aus
Plugin- und lokalem Tool-Namen entstehen:

```text
Plugin: catalog
Method: search
LLM-facing name: catalog_search
```

Entsprechend gilt:

```python
await tools.execute("catalog_search", {"query": "mechanical keyboard"})
```

Der einzelne Descriptor sollte zusätzlich strukturierte Herkunftsinformationen
tragen:

```python
tool.plugin_name    # "catalog"
tool.local_name     # "search"
tool.name           # "catalog_search"
```

Das erlaubt später Filter wie „nur das `catalog`-Plugin“, aussagekräftige
Kollisionsfehler und provider-spezifische Namensadapter. Ein frei wählbarer
Separator oder ein optionales Prefix würden Version 1 unnötig mehrdeutig
machen. `plugin_name + "_" + local_name` ist einfach und mit den üblichen
Function-Calling-Schemas kompatibel.

Die Registry validiert das Plugin vollständig, bevor sie eine Methode
registriert. Bei einer Kollision wird nichts teilweise hinzugefügt.

## Dependency Injection: zwei Ebenen

Constructor Injection und `Inject[T]` lösen unterschiedliche Lifecycle-
Probleme und sollten nebeneinander bestehen.

### 1. Constructor Injection für langlebige Services

Dependencies, die über die gesamte Lebenszeit eines Plugins stabil bleiben,
gehören in den Konstruktor:

```python
class CatalogPlugin:
    def __init__(self, service: CatalogService, logger: Logger) -> None:
        self._service = service
        self._logger = logger
```

Das sind typischerweise:

- Application Services,
- stateless Domain Services,
- Clients und Repositories mit `APP`-Lifecycle,
- Logger, Konfiguration und Policies.

Der Vorteil ist, dass das Plugin vollständig und explizit konstruiert ist. Es
gibt keinen Service-Locator-Aufruf innerhalb seiner Methoden, und Tests können
Fakes direkt übergeben.

### 2. Methoden-Injection für kurze Scopes

Call- oder Turn-spezifische Werte dürfen nicht im langlebigen Plugin-Objekt
gefangen werden. Sie bleiben als `Inject[T]` in der Tool-Methode:

```python
class OrdersPlugin:
    def __init__(self, orders: OrderService) -> None:
        self._orders = orders

    @tool("Cancel an order")
    async def cancel(
        self,
        order_id: str,
        user: Inject[CurrentUser],       # TURN
        transaction: Inject[Transaction],  # CALL
    ) -> Cancellation:
        return await self._orders.cancel(
            order_id,
            actor=user,
            transaction=transaction,
        )
```

Diese Parameter erscheinen wie bisher nicht im Modell-Schema. Der vorhandene
`DependencyContainer` löst sie beim konkreten Aufruf im aktiven Scope auf.

Damit ist die Regel einfach:

```text
APP-stabil und Teil des Plugin-Aufbaus  → Konstruktor
TURN-/CALL-spezifisch                   → Inject[T] an der Methode
LLM-generiert                           → normaler Methodenparameter
```

## Zwei Registrierungsmodi

### Explizite Instanz: Version 1 und empfohlener Default

```python
tools.add_plugin(
    CatalogPlugin(catalog_service, recommendation_service),
    name="catalog",
)
```

Hier ist der Composition Root der Anwendung für die Konstruktion
verantwortlich. Das funktioniert mit jedem externen DI-Framework und benötigt
keine zusätzliche Magie in `agenttoolkit`. Die Plugin-Instanz lebt mindestens
so lange wie ihre Registrierung; ihre extern erzeugten Dependencies werden
nicht von `Tools` beendet.

Dieser Modus sollte zuerst implementiert werden. Er liefert bereits die
gewünschte Enterprise-Struktur und Constructor Injection.

### Container-aktivierte Klasse: mögliche Version 2

Als Ergonomie-Erweiterung kann `add_plugin` später auch einen Typ akzeptieren:

```python
class Dependencies(DependencyProvider):
    @provide(scope=Scope.APP)
    def catalog_service(self, client: SearchClient) -> CatalogService:
        return CatalogService(client)

    @provide(scope=Scope.APP)
    def recommendations(self) -> RecommendationService:
        return RecommendationService()


tools = Tools(dependencies=[Dependencies()])
tools.add_plugin(CatalogPlugin, name="catalog")
```

Dann würde der Container die typannotierten Konstruktorparameter auflösen und
genau eine Plugin-Instanz im `APP`-Scope aktivieren.

Für diesen Modus gelten harte Regeln:

- Jeder Konstruktorparameter braucht eine Typannotation.
- Jede Constructor Dependency muss im Container definiert sein.
- Constructor Dependencies müssen `APP`-Scope haben.
- `TURN`- und `CALL`-Dependencies sind im Konstruktor verboten und gehören in
  die Tool-Methode.
- Das Plugin selbst lebt im `APP`-Scope.
- Der Dependency-Graph wird bereits beim Hinzufügen des Plugin-Typs validiert.

Schemas können vor der Aktivierung aus den ungebundenen, dekorierten Methoden
gebildet werden. Die Instanz wird erst innerhalb des aktiven `APP`-Scopes
benötigt. Intern braucht es dafür einen kleinen Plugin-Activator; der normale
Tool-Execution-Pfad bleibt danach unverändert.

Dieser zweite Modus ist nützlich, sollte aber nicht Voraussetzung für die
klassenbasierte API sein. Sonst werden Plugin-Discovery, asynchroner
Container-Lifecycle und Tool-Registrierung unnötig in einem ersten Schritt
gekoppelt.

## Plugin-Lifecycle und Parallelität

Eine registrierte Plugin-Instanz ist langlebig und kann gleichzeitig von
mehreren Tool-Calls verwendet werden. Deshalb gilt:

- Plugin-Instanzen sollten grundsätzlich stateless sein.
- Unveränderliche Konfiguration und Service-Referenzen dürfen auf `self`
  liegen.
- Mutable Caches müssen concurrency-safe sein.
- Request-, User-, Turn- und Transaktionszustand gehört in scoped Dependencies.
- Ein Plugin ist kein Ersatz für `DependencyProvider` und besitzt nicht den
  Cleanup seiner Services.

`Tools` führt weiterhin jeden einzelnen Plugin-Tool-Call durch dieselbe
Middleware-Kette und öffnet dabei automatisch den `CALL`-Scope. Ein Plugin hat
keine separate Execution-Pipeline.

## Direkte Testbarkeit

Die Plugin-Klasse bleibt ohne Registry testbar:

```python
async def test_catalog_search_delegates_to_service() -> None:
    service = FakeCatalogService()
    plugin = CatalogPlugin(service, FakeRecommendationService())

    result = await plugin.search("keyboards", limit=5)

    assert result == service.products
    assert service.last_query == "keyboards"
```

Ein Integrationstest über `Tools.execute` deckt zusätzlich Schema-Validierung,
Namespacing, scoped Injection und Middleware ab:

```python
assert await tools.execute(
    "catalog_search",
    {"query": "keyboards", "limit": 5},
) == expected
```

## Abbildung auf die bestehende Registry

Die vorhandene Architektur kann fast vollständig wiederverwendet werden:

```text
@tools.tool-Funktion ───────────────┐
                                   │
Plugin-Instanz                     │
 ├── @tool search() ──┐            │
 ├── @tool get() ─────┼── Reflection
 └── private helper   ─┘            │
                 │                  │
                 ▼                  ▼
             Tool-Descriptor pro Funktion
                         │
                         ▼
       Registry → Schema → Middleware → execute
```

Für eine gebundene Plugin-Methode ist `self` bereits gebunden. Die bestehende
Signatur- und Pydantic-Logik kann daher Parameter und `Inject[T]` genauso
behandeln wie bei einer freien Funktion.

Neu benötigt werden konzeptionell nur:

- ein module-level `@tool` als reiner Metadata Decorator,
- `Tools.add_plugin(instance, *, name)`,
- atomare Discovery und Registrierung markierter Methoden,
- Plugin-Herkunft und deterministisches Namespacing im `Tool`-Descriptor,
- optional später ein Container-basierter Activator für Plugin-Typen.

`get_schema`, `create_tool_models`, `execute`, Middleware, Error Boundary und
Scope-Handling brauchen keinen parallelen Plugin-spezifischen Pfad.

## Validierung

`add_plugin` sollte die gesamte Gruppe vor der Mutation der Registry prüfen:

- Der Plugin-Name ist vorhanden und für Tool-Namen verwendbar.
- Mindestens eine Methode trägt `@tool`.
- Jeder lokale Tool-Name ist innerhalb des Plugins eindeutig.
- Jeder resultierende globale Name ist in der Registry eindeutig.
- Markierte Methoden sind gebundene Instanzmethoden; `staticmethod` und
  `classmethod` werden in Version 1 abgelehnt.
- Signaturen erfüllen dieselben Regeln wie freie Tools, insbesondere keine
  variadischen Parameter.
- Pydantic-Inputmodelle und `Inject[T]` sind eindeutig bindbar.
- Die Registrierung ist atomar: Bei einem Fehler bleibt die Registry
  unverändert.

Bei container-aktivierten Plugin-Typen kommen die Constructor- und Scope-
Prüfungen hinzu.

## Vererbung

Für Version 1 sollte eine einfache Regel gelten:

- Geerbte dekorierte Methoden werden exponiert.
- Überschreibt eine Unterklasse eine dekorierte Methode, muss sie die neue
  Methode erneut mit `@tool` markieren.
- Eine nicht dekorierte Überschreibung entfernt das Tool bewusst aus dem
  Plugin.

Das verhindert, dass eine normale Python-Überschreibung versehentlich mit
veralteten Metadaten der Basisklasse öffentlich bleibt.

## Empfohlene erste Ausbaustufe

Die erste Implementierung sollte bewusst klein bleiben:

1. Die bestehende `@tools.tool`-API bleibt unverändert.
2. Ein neuer module-level Decorator `@tool` speichert dieselben Metadaten, ohne
   zu registrieren.
3. `tools.add_plugin(instance, name="...")` registriert alle markierten,
   gebundenen Methoden atomar.
4. Plugin-Namen werden als Prefix der modellseitigen Tool-Namen verwendet und
   strukturiert am Descriptor gespeichert.
5. Constructor Injection erfolgt zunächst explizit am Composition Root.
6. Kurze Lifecycles verwenden weiterhin `Inject[T]` an Tool-Methoden.

Container-aktivierte Plugin-Typen und weitere Plugin-Quellen können danach
separat ergänzt werden. Plugin-Level-Metadaten und Plugin-Filter gehören nicht
zum Umfang von Version 1.

Damit entsteht genau die gewünschte Zweiteilung:

```text
klein und direkt                  strukturiert und enterprise-tauglich

@tools.tool(...)                 class CatalogPlugin:
def search(...):                     @tool(...)
    ...                              def search(...): ...

                                 tools.add_plugin(
                                     CatalogPlugin(services...),
                                     name="catalog",
                                 )
```

Beide Oberflächen enden im selben `Tool`-Descriptor und besitzen dadurch exakt
dasselbe Verhalten gegenüber LLM-Providern und zur Laufzeit.
