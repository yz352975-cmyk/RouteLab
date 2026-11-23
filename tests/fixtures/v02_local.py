def solve(ctx):
    # 局部视野：当前节点只知道邻居及其通告。
    choices = [n for n in ctx["neighbors"]
               if n["up"] and n["allowed"] and n["authenticated"] and n["to"] not in ctx["visited"]]
    if not choices:
        return None
    best = min(choices, key=lambda n: n["cost"] + n["estimate"])
    return best["to"]
