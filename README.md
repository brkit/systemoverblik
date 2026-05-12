## Hvorfor vise et overblik over systemer når Kitos gør det?
Fordi man i digitalisering ikke ønsker at oprette alle i Kitos. Det ville være en administrativ byrde. 

## Referencer
`S2505-541`, `S2505-7363`

## API docs

[Kitos API docs](https://os2web.atlassian.net/wiki/spaces/KITOS/pages/658145384/S+dan+kommer+du+igang)


## Docs 
`main.py` fetcher data fra Kitos API. Følgende felter bliver splejset sammen til 1 json fil: `name`, `description`, `supplier`, `responsibleOrganizationUnit`, `usingOrganizationUnits`, `roles`, `externalReferences`.

`index.html` viser data ved hjælp af [fusejs](https://www.fusejs.io/) og [picocss](https://picocss.com/)


## Kør programmet

- Installer dependencies fx. med [uv](https://docs.astral.sh/uv/)
- placer fuse.js og pico.min.css filerne i en dist mappe. 
- run `uv run main.py` og se din færdige index.html fil i dist mappen.

