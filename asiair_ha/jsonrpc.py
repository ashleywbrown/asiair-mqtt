""" JSON-RPC Utility Functions """

def make_command(id, command):
    if isinstance(command, tuple):
        (method, params) = command
        return {"id": id, "method": method, "params": params}
    else:
        return {"id": id, "method": command}
