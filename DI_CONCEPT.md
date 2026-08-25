# Dependency Injection: API-Vorschlag

## Entscheidungen

- Die neue DI-API ist die einzige unterstützte API. `ToolContext` entfällt.
- Dependency-Definitionen, Container-Lifecycle und Tool-Registrierung bleiben
  getrennt.
- Tools werden mit `@tools.tool` dekoriert. `tools.register(...)` registriert
  bereits erzeugte `Tool`-Objekte imperativ.
- Die eingebauten Scopes sind `APP`, `TURN` und `CALL`.
- `CALL` ist der Default-Scope.
- Benutzerdefinierte Scopes sind zunächst nicht vorgesehen.

## Naming

`Provider` ist im Kontext eines Agent-Toolkits zu unspezifisch. Der vollständige
Name `DependencyProvider` macht dagegen unmittelbar klar, was bereitgestellt
wird. Innerhalb dieses Kontexts bleibt `@provide` als kurzer Decorator
verständlich.

```python
from agenttoolkit import (
    DependencyProvider,
    Inject,
    Scope,
    Tools,
    provide,
)
```

Die Rollen sind bewusst getrennt:

- `DependencyProvider` definiert, wie Dependencies erzeugt werden.
- `Tools` registriert Tools und besitzt intern Container, Scopes und Lebensdauer.

## Ziel-API

```python
from collections.abc import AsyncIterator

from agenttoolkit import (
    DependencyProvider,
    Inject,
    Scope,
    Tools,
    provide,
)


class AppDependencyProvider(DependencyProvider):
    @provide(scope=Scope.APP)
    def settings(self) -> Settings:
        return Settings.from_env()

    @provide(scope=Scope.APP)
    def spotify(self, settings: Settings) -> SpotifyClient:
        return SpotifyClient(
            client_id=settings.spotify_client_id,
            client_secret=settings.spotify_client_secret,
        )

    @provide(scope=Scope.APP)
    def player(self, spotify: SpotifyClient) -> MusicPlayer:
        return MusicPlayer(spotify)

    @provide(scope=Scope.TURN)
    def turn_state(self) -> TurnState:
        return TurnState()

    @provide  # Scope.CALL ist der Default
    async def connection(self, database: Database) -> AsyncIterator[Connection]:
        connection = await database.connect()
        try:
            yield connection
        finally:
            await connection.close()


tools = Tools(
    dependencies=[
        AppDependencyProvider(),
        DatabaseDependencyProvider(),
    ]
)


@tools.tool("Search for a track")
async def search_tracks(
    query: str,
    spotify: Inject[SpotifyClient],
) -> list[Track]:
    return await spotify.search(query)


@tools.tool("Play a track", requires_approval=True)
async def play(
    track_id: str,
    player: Inject[MusicPlayer],
    connection: Inject[Connection],
    turn: Inject[TurnState],
) -> str:
    await player.play(track_id)
    await connection.record_play(track_id)
    turn.played_tracks.append(track_id)
    return "Playing"
```

Nur normale Parameter wie `track_id` erscheinen im Modell-Schema.
`Inject[T]` markiert eindeutig die Parameter, die aus dem Dependency-Graph
aufgelöst werden. Die Entscheidung hängt damit nicht von zufällig
registrierten Typen ab.

## Verwendung und Lebensdauer

```python
async with tools:  # APP öffnen
    async with tools.scope(Scope.TURN):
        await tools.execute("search_tracks", {"query": "Massive Attack"})
        await tools.execute("play", {"track_id": "abc"})
```

Die Scope-Hierarchie ist:

```text
APP
└── TURN
    ├── CALL: search_tracks
    └── CALL: play
```

- `APP` lebt vom Eintritt in `async with tools` bis zum Herunterfahren der
  Anwendung.
- `TURN` wird explizit geöffnet und kann mehrere sequenzielle oder parallele
  Tool-Aufrufe eines Agent-Turns umfassen.
- `CALL` wird von `tools.execute()` automatisch geöffnet und danach wieder
  geschlossen.

`CALL` als Default bedeutet: Eine Dependency wird innerhalb eines Tool-Aufrufs
höchstens einmal erzeugt und danach wieder verworfen. Der nächste Tool-Aufruf
erhält eine neue Instanz. Einen zusätzlichen, ungecachten »Transient«-Modus
braucht die erste Version nicht.

Wird kein `TURN` geöffnet, dürfen Tools weiterhin ausgeführt werden, solange
sie keine `TURN`-Dependency benötigen. Der Versuch, `TurnState` ohne aktiven
`TURN`-Scope aufzulösen, liefert einen klaren Fehler.

Generator-Provider sind Lifecycle-Hooks. Code nach `yield` wird beim Verlassen
des jeweiligen Scopes auch nach einem Fehler ausgeführt. Synchrone und
asynchrone Factorys sowie Generatoren werden unterstützt.

## Validierung

`Tools(...)` baut intern den Container und validiert den Dependency-Graph.
Folgende
Fehler sollen dadurch bereits beim Start sichtbar werden:

- fehlende oder doppelte Dependency-Definitionen,
- zyklische Abhängigkeiten,
- ungültige Scope-Abhängigkeiten, etwa `APP` von `CALL`,

Ein kurzlebiger Scope darf Dependencies aus seinen übergeordneten Scopes
verwenden. Die umgekehrte Richtung ist nicht erlaubt.

`Tools` validiert davon unabhängig weiterhin seine Tool-Registrierungen, etwa
mehrere Tools mit demselben Namen.

Der Container ist ein Implementierungsdetail von `Tools`. Anwendungen
arbeiten nur mit `DependencyProvider`, `Tools`, `Scope` und `Inject`.

## Entscheidung zum TURN-Scope

Eine benötigte `TURN`-Dependency verlangt immer einen explizit geöffneten
Scope. Ein fehlender `TURN` wird nicht automatisch für einen einzelnen
`execute()`-Aufruf erzeugt.
