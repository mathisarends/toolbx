import pytest

from agenttoolkit.builtins import (
    InMemoryTodoList,
    TodoList,
    TodoNotFoundError,
    TodoStateError,
    TodoStatus,
)


@pytest.mark.asyncio
async def test_todo_list_tracks_a_checklist() -> None:
    todos = InMemoryTodoList()
    assert isinstance(todos, TodoList)

    await todos.add("Inspect code")
    implementation = await todos.add("Implement feature")
    active = await todos.update(
        implementation.id,
        status=TodoStatus.IN_PROGRESS,
    )
    assert active.status is TodoStatus.IN_PROGRESS

    completed = await todos.complete(active.id)
    assert completed.status is TodoStatus.COMPLETED
    assert [todo.content for todo in await todos.list()] == [
        "Inspect code",
        "Implement feature",
    ]
    assert await todos.list(status=TodoStatus.COMPLETED) == (completed,)


@pytest.mark.asyncio
async def test_todo_list_updates_removes_and_clears_items() -> None:
    todos = InMemoryTodoList()
    first = await todos.add("First")
    second = await todos.add("Second")

    renamed = await todos.update(first.id, content="Renamed")
    await todos.complete(second.id)
    assert renamed.content == "Renamed"
    assert await todos.clear(completed_only=True) == 1
    assert await todos.remove(first.id) == renamed
    assert await todos.clear() == 0

    with pytest.raises(TodoNotFoundError, match=str(first.id)):
        await todos.complete(first.id)


@pytest.mark.asyncio
async def test_todo_list_validates_state_and_input() -> None:
    todos = InMemoryTodoList()
    first = await todos.add("First", status=TodoStatus.IN_PROGRESS)
    second = await todos.add("Second")

    with pytest.raises(TodoStateError, match="only one"):
        await todos.update(second.id, status=TodoStatus.IN_PROGRESS)
    with pytest.raises(ValueError, match="must be provided"):
        await todos.update(first.id)
    with pytest.raises(ValueError, match="must not be empty"):
        await todos.add(" ")
    with pytest.raises(TypeError, match="TodoStatus"):
        await todos.add("Third", status="pending")  # type: ignore[arg-type]
