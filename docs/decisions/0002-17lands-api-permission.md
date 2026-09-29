# 0002: Ask 17Lands before polling its JSON endpoints

Status: **pending**. The owner posts the request below on the 17Lands Discord (linked from
https://www.17lands.com/usage_guidelines) and records the reply here with its date.
Opened 2026-09-28.

## Consulted

data-source-steward (planning panel, 2026-09-28), with the text of the 17Lands usage
guidelines and Terms of Service read from the site bundle because the pages are rendered
by JavaScript.

## Why this is needed

- The usage guidelines say: "Unless you've gotten explicit permission otherwise, we
  discourage automated scraping of our API ... we provide no guarantees that any part of
  the API will remain consistent ... Instead, we love when people make use of the public
  data dumps."
- The Terms of Service say: "You may not obtain or attempt to obtain any materials or
  information through any means not intentionally made available or provided for through
  the Site." The JSON endpoints are undocumented.
- The guidelines also ask third-party tools not to present a new expansion's data "until
  the 12th day it has been released on MTG Arena (typically the second Monday after the set
  release)".

## Decision until an answer arrives

- The public game files (CC BY 4.0) are the only 17Lands source the app reads.
- The endpoint adapter ships disabled and refuses to run unless this record says yes and
  `config/sources.yaml` records the grant.
- Every set carries `embargo_until = arena_release_date + 11 days` (FRA: 2026-10-10), and
  17Lands-derived views of a set are not shown before it.

## The request to post

> Hi 17Lands team. I'm building a free, open-source tool
> (https://github.com/liamH47/arena-wizard) that recommends Bo1 sealed decks for a small
> private group of friends. It is calibrated on your public game datasets, credited with
> links at the top of every page under CC BY 4.0, and never calls your site on behalf of a
> user request: everything is mirrored on a schedule.
>
> 1. May it poll `color_ratings/data` and `card_ratings/data` once per UTC day for up to
>    three current sets (at most 9 requests a day, User-Agent
>    `arena-wizard/0.1 (+https://github.com/liamH47/arena-wizard)`), plus
>    `card_ratings/data?format=ArenaDirect_Sealed` every 6 hours only while an Arena Direct
>    is running?
> 2. For the new-set embargo, Reality Fracture reached Arena on 2026-09-29. We read "the
>    12th day" as 2026-10-10. Is that right, or do you mean the second Monday, 2026-10-12?
>
> If the answer to the first question is no, we'll use only the public datasets. Thanks for
> the data and the tools.

## What changes with each answer

- **Yes:** record the date, who answered, and the scope granted here and in
  `config/sources.yaml`; the adapter runs within exactly that scope, and the weekly
  contract check covers the endpoints.
- **No, or no answer:** nothing changes. Live-set trends and bombs wait for the public
  files, roughly three weeks after release; until then a set runs on expert ratings,
  curated bombs, castability, and curve, all labelled.
- **A different embargo date:** update `EMBARGO_DAYS` in `domain/sets.py` and its test in
  the same change.
