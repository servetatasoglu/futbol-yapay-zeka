from generate_dashboard import load_team_form, get_form, clean_team_name

cache = load_team_form()
print("Cache size:", len(cache))
print("All teams in cache:", list(cache.keys()))

# Test some names
teams_to_test = ["Elversberg", "SC Preußen Münster", "FC Porto", "Brest", "Strasbourg", "Trabzonspor"]
for t in teams_to_test:
    clean = clean_team_name(t)
    res = get_form(cache, clean)
    print(f"Form for {t} ({clean}): {res}")
