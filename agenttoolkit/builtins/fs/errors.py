class WorkspaceError(Exception):
    pass


class PathOutsideWorkspaceError(WorkspaceError, ValueError):
    pass


class FileTooLargeError(WorkspaceError):
    pass


class EditError(WorkspaceError, ValueError):
    pass
