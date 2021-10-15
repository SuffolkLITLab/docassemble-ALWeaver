# Assembly Line Weaver

A tool to help generate draft interviews for the docassemble platform. Tightly linked to https://github.com/SuffolkLITLab/docassemble-AssemblyLine. Currently linked to https://github.com/SuffolkLITLab/docassemble-MassAccess but moving to be more jurisdiction independent.

## History

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
