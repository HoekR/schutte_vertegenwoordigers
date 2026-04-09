import pyphen
h = pyphen.Pyphen(lang='nl_NL')

pairs = [
    ('commis','saris'),
    ('Noord','Holland'),
    ('Poi','tou'),
    ('Groene','velt'),
    ('ge','depu'),
    ('ambas','sadeur'),
    ('Ka','tho'),
    ('pen','sio'),
]
for prev, rest in pairs:
    candidate = prev + rest
    positions = h.positions(candidate)
    join_pos = len(prev)
    is_valid = join_pos in positions
    print(f"{prev}-{rest} => {candidate!r:20} breaks@{positions}  join_at={join_pos} valid_break={is_valid}")
