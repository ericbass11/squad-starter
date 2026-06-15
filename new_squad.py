"""
Cria um squad novo a partir do starter. Dois modos:

  Interativo (pergunta no terminal):
      python new_squad.py

  Por arquivo (preenche um YAML e gera):
      python new_squad.py --from scaffolding/spec.example.yaml

Em ambos, o esqueleto é fixo: orchestrator-worker + QA + checkpoint humano no fim.
O resultado é validado contra o schema antes de gravar.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from scaffolding.generator import AgentSpec, SquadSpec, generate  # noqa: E402


def _from_file(path: str) -> SquadSpec:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    agents = [AgentSpec(**a) for a in raw.pop("agents", [])]
    return SquadSpec(agents=agents, **raw)


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or default


def _interactive() -> SquadSpec:
    print("== Novo squad (orchestrator-worker + checkpoint humano) ==\n")
    name = _ask("Nome (kebab-case, ex.: osint-investigador)")
    desc = _ask("Descrição (uma frase)")
    context = _ask("Contexto (audax/externo/pessoal)", "audax")
    agents: list[AgentSpec] = []
    print("\nAgentes de trabalho (enter no nome para encerrar):")
    i = 1
    while True:
        an = _ask(f"  Agente {i} — nome (ex.: AG{i})")
        if not an:
            break
        role = _ask("    papel (curto)")
        srcs = _ask("    fontes separadas por vírgula (ex.: SQL,SCR)")
        tier = _ask("    model_tier (fast/powerful)", "powerful")
        agents.append(AgentSpec(name=an, role=role,
                                sources=[s.strip() for s in srcs.split(",") if s.strip()],
                                model_tier=tier))
        i += 1
    return SquadSpec(name=name, description=desc, context=context, agents=agents)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_file", help="caminho de um spec.yaml")
    args = ap.parse_args()

    spec = _from_file(args.from_file) if args.from_file else _interactive()

    try:
        target = generate(spec)
    except Exception as e:  # noqa: BLE001
        print(f"\n✗ falhou: {e}")
        return 1

    rel = target.relative_to(target.parent.parent)
    print(f"\n✓ squad criado em {rel}/")
    print("  próximos passos:")
    print(f"    1. edite {rel}/SQUAD.md (condição de término, vetos do domínio)")
    print(f"    2. implemente os agentes em {rel}/agents/__init__.py (troque os stubs)")
    print(f"    3. registre os agentes no run.py do squad e rode")
    print("    4. python scripts/validate_squads.py && pytest -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
