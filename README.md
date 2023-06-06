# Assembly Line Weaver: Suffolk LIT Lab Document Assembly Line

[![PyPI version](https://badge.fury.io/py/docassemble.ALWeaver.svg)](https://badge.fury.io/py/docassemble.ALWeaver)

<img src="https://user-images.githubusercontent.com/7645641/142245862-c2eb02ab-3090-4e97-9653-bb700bf4c54d.png" alt="drawing of two cartoon people collaborating on building a web application" width="300" style="align: center;"/>

The Assembly Line Project is a collection of volunteers, students, and institutions who joined together
during the COVID-19 pandemic to help increase access to the court system. Our vision is mobile-friendly,
easy to use **guided** online forms that help empower litigants to access the court remotely.

Our signature project is [CourtFormsOnline.org](https://courtformsonline.org).

We designed a step-by-step, assembly line style process for automating court forms on top of Docassemble
and built several tools along the way that **you** can use in your home jurisdiction.

This package contains an **automation and rapid prototyping tool** to support authoring robust,
consistent, and attractive Docassemble interviews that help complete court forms. Upload a labeled
PDF or DOCX file, and the Assembly Line Weaver will produce a runnable, clean code, draft of a
Docassemble interview that you can continue to edit and refine.

Read more on our [documentation page](https://suffolklitlab.org/docassemble-AssemblyLine-documentation/).


## Related repositories

* https://github.com/SuffolkLitLab/docassemble-AssemblyLine
* https://github.com/SuffolkLitLab/docassemble-ALMassachusetts
* https://github.com/SuffolkLitLab/docassemble-MassAccess
* https://github.com/SuffolkLitLab/docassemble-ThemeTemplate
* https://github.com/SuffolkLitLab/EfileProxyServer

## Documentation

https://suffolklitlab.org/docassemble-AssemblyLine-documentation/

## History

See [the CHANGELOG](CHANGELOG.md) for more information.

## Authors

Quinten Steenhuis, qsteenhuis@suffolk.edu  
Michelle  
Bryce Willey, bwilley@suffolk.edu
Lily  
David Colarusso  
Nharika Singh  

## Installation requirements

### Using auto drafting mode

As of June 2023, the Weaver includes auto drafting mode.

To use the automatic field grouping feature of auto drafting mode,
you need to install either:

1. The `en_core_web_lg` model on your server, or
2. An API token for tools.suffolklitlab.org.

You can request an API token by emailing massaccess@suffolklitlab.org. If you
prefer to install your own copy of the `en_core_web_lg` model, you can
access it the first time you select to use auto drafting mode when logged
in as an administrator.