from conftest import tool_names_offered, tool_results, tools_offered
from factories import assistant_message, tool_call


def skill_tool(httpserver) -> dict:
    (tool,) = [t for t in tools_offered(httpserver) if t["name"] == "skill"]
    return tool


def test_discovers_skills_and_offers_them_as_one_tool(
    ijon, httpserver, openai_endpoint, tmp_path, write_skill
):
    skills = tmp_path / ".agents" / "skills"
    write_skill(skills, "beta", "# Beta\n\nbody")
    write_skill(skills, "alpha", "# Alpha\n\nbody")
    openai_endpoint(assistant_message("done"))

    result = ijon.run("hi", "--model", "test-model", "--skills", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert tool_names_offered(httpserver) == ["skill"]
    tool = skill_tool(httpserver)
    assert tool["parameters"]["properties"]["name"]["enum"] == ["alpha", "beta"]
    assert tool["parameters"]["required"] == ["name"]


def test_no_skill_tool_without_skills(ijon, httpserver, openai_endpoint, tmp_path):
    openai_endpoint(assistant_message("done"))

    result = ijon.run("hi", "--model", "test-model", "--skills", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert tool_names_offered(httpserver) == []


def test_ignores_directories_without_a_skill_file(
    ijon, httpserver, openai_endpoint, tmp_path, write_skill
):
    skills = tmp_path / ".agents" / "skills"
    write_skill(skills, "real")
    (skills / "empty").mkdir()
    (skills / "stray.md").write_text("not a skill")
    openai_endpoint(assistant_message("done"))

    ijon.run("hi", "--model", "test-model", "--skills", cwd=tmp_path)

    assert skill_tool(httpserver)["parameters"]["properties"]["name"]["enum"] == [
        "real"
    ]


def test_description_comes_from_the_first_heading(
    ijon, httpserver, openai_endpoint, tmp_path, write_skill
):
    skills = tmp_path / ".agents" / "skills"
    write_skill(skills, "greet", "\n\n## Say hello nicely\n\nbody")
    openai_endpoint(assistant_message("done"))

    ijon.run("hi", "--model", "test-model", "--skills", cwd=tmp_path)

    assert "- greet: Say hello nicely" in skill_tool(httpserver)["description"]


def test_frontmatter_overrides_name_and_description(
    ijon, httpserver, openai_endpoint, tmp_path, write_skill
):
    skills = tmp_path / ".agents" / "skills"
    write_skill(
        skills,
        "dir-name",
        "---\nname: Cool Skill\ndescription: Does cool things\n---\n# Heading\n\nbody",
    )
    openai_endpoint(assistant_message("done"))

    ijon.run("hi", "--model", "test-model", "--skills", cwd=tmp_path)

    tool = skill_tool(httpserver)
    assert tool["parameters"]["properties"]["name"]["enum"] == ["Cool Skill"]
    assert "- Cool Skill: Does cool things" in tool["description"]


def test_frontmatter_without_description_falls_back_to_heading(
    ijon, httpserver, openai_endpoint, tmp_path, write_skill
):
    skills = tmp_path / ".agents" / "skills"
    write_skill(
        skills, "dir-name", "---\nname: Cool Skill\n---\n# Heading Desc\n\nbody"
    )
    openai_endpoint(assistant_message("done"))

    ijon.run("hi", "--model", "test-model", "--skills", cwd=tmp_path)

    assert "- Cool Skill: Heading Desc" in skill_tool(httpserver)["description"]


def test_loading_a_skill_returns_its_full_content(
    ijon, openai_endpoint, tmp_path, write_skill
):
    content = "---\nname: alpha\n---\n# Alpha\n\nalpha body"
    write_skill(tmp_path / ".agents" / "skills", "alpha", content)
    openai_endpoint(tool_call({"name": "alpha"}, name="skill"), assistant_message("ok"))

    result = ijon.run(
        "hi", "--model", "test-model", "--skills", "--jsonl", cwd=tmp_path
    )

    assert result.returncode == 0, result.stderr
    assert tool_results(result)[0]["content"] == content


def test_reports_unknown_skill(ijon, openai_endpoint, tmp_path, write_skill):
    write_skill(tmp_path / ".agents" / "skills", "alpha")
    openai_endpoint(tool_call({"name": "ghost"}, name="skill"), assistant_message("ok"))

    result = ijon.run(
        "hi", "--model", "test-model", "--skills", "--jsonl", cwd=tmp_path
    )

    assert "unknown skill 'ghost'" in tool_results(result)[0]["content"]


def test_reports_missing_skill_name(ijon, openai_endpoint, tmp_path, write_skill):
    write_skill(tmp_path / ".agents" / "skills", "alpha")
    openai_endpoint(tool_call({}, name="skill"), assistant_message("ok"))

    result = ijon.run(
        "hi", "--model", "test-model", "--skills", "--jsonl", cwd=tmp_path
    )

    assert "no skill name provided" in tool_results(result)[0]["content"]
