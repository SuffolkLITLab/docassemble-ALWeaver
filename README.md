# Assembly Line Weaver: Suffolk LIT Lab Document Assembly Line

<img src="https://user-images.githubusercontent.com/7645641/142245862-c2eb02ab-3090-4e97-9653-bb700bf4c54d.png" alt="drawing" width="300" alt="work together" style="align: center;"/>

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


# Related repositories

* https://github.com/SuffolkLitLab/docassemble-AssemblyLine
* https://github.com/SuffolkLitLab/docassemble-ALMassachusetts
* https://github.com/SuffolkLitLab/docassemble-MassAccess
* https://github.com/SuffolkLitLab/docassemble-ALGenericJurisdiction
* https://github.com/SuffolkLitLab/EfileProxyServer

# Documentation

https://suffolklitlab.org/docassemble-AssemblyLine-documentation/

## History
* 2021-11-03
    * Add support for *plural* names for people in PDF files

* 2021-10-15
    * Handle overflow in addendum
    * Multiple choice radio/checkbox fields
    * DOCX validation
* 2021-09-09
    * Improved internationalization
    * Simplified PDF checker
* 2021-04-14 Multiple fixes:
    * Migrated to more flexible Mako template structure for generated 
      interview blocks
    * Package can be installed (for test purposes) after being
      generated
    * Various refactors and code cleanup
    * Simplified and improved generated code and order of blocks
    * Added version number/date stamp to generated code

* 2021-03-09 Extensive improvements:
    * Improvements to review screens
    * Question/field editing and reordering
    * Improvements to YAML structure
    * Generate interstitial screens
    * Refactoring and bug fixes
* 2021-02-09 Combine yes/no variables; more flexible handling of people variables and assistance with gathering varying numbers w/ less code
* 2021-01-29 Bug fixes; migration to AssemblyLine complete
* 2021-01-25 Bug fixes, start migration to [AssemblyLine](https://github.com/SuffolkLITLab/docassemble-AssemblyLine) dependency and away from MAVirtualCourt

## Authors

Quinten Steenhuis, qsteenhuis@suffolk.edu  
Michelle  
Bryce Willey  
Lily  
David Colarusso  
Nharika Singh  

## Installation requirements

* Create a Docassemble API key and add it your configuration like this:
```
install packages api key: 123458abcdefghijlklmno99A
```
