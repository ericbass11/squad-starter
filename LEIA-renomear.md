# LEIA — renomear depois de subir (3 itens)

Esta versão tem 3 itens renomeados porque o upload web do GitHub não aceita
arrastar arquivos/pastas que começam com ponto. Depois de subir tudo, renomeie
no próprio GitHub (Add file / editar → mudar o nome de volta):

| Subiu como        | Renomeie para  |
|-------------------|----------------|
| dot-gitignore     | .gitignore     |
| dot-env.example   | .env.example   |
| dot-github/       | .github/       |

Como renomear pelo site: abra o arquivo no GitHub → ícone de lápis (editar) →
mude o nome no topo (ex.: apague "dot-gitignore" e digite ".gitignore") →
Commit changes. Para a pasta dot-github, ao editar o arquivo dentro dela
(dot-github/workflows/squad-ci.yml) troque o caminho para
.github/workflows/squad-ci.yml — o GitHub recria a pasta com o ponto.

Depois de renomear os 3, apague este arquivo. Pronto.

Obs.: enquanto não renomear, o CI (.github) não roda e o .gitignore não protege
— mas o código (python run.py / pytest) funciona normalmente.
