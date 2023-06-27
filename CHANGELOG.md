# CHANGELOG

## For revisions after v1.9.0, see https://github.com/SuffolkLITLab/docassemble-ALWeaver/releases/

## Version v1.9.0

### New

* Radio buttons in weaver by @BryceStevenWilley in [PR 754](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/754)

### Fixed

* Fix bug affecting mixed document types in multiweaver by @nonprofittechy in [PR 742](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/742)
* Correct logic for finding PDF field bbox by @BryceStevenWilley in [PR 758](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/758)
* Close PDF objects when done by @BryceStevenWilley in [PR 760](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/760)
* Removed pypdf2 by @BryceStevenWilley in [PR 749](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/749)

### Internal Cleanup

* Update python test action by @BryceStevenWilley in [PR 743](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/743)
* Add pyproject.toml for black formatting rules by @BryceStevenWilley in [PR 751](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/751)
* Format Python code with psf/black push by @github-actions in [PR 755](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/755)


## Version v1.8.0

### New
* Made a partial API for the "I'm feeling Lucky" feature by @nonprofittechy in [PR 735](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/735)

### Changed

* Collect addresses before putting them in a list by @BryceStevenWilley in [PR 697](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/697)
* Set user_ask_role directly in additional to user_role by @BryceStevenWilley in [PR 698](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/698)
* Don't show typical_role if form_type = starts_case by @BryceStevenWilley in [PR 706](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/706)
* Warn, don't block use of reserved keywords in DOCX templates by @nonprofittechy in [PR 708](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/708)

### Fixed
* Let a DOCX template contain a zero-based index by @nonprofittechy in [PR 695](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/695), and [PR 702](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/702)
* Don't tell DOCX users they can't use 0 idx in PDF by @BryceStevenWilley
* Ignore push buttons in PDFs instead of raising an error by @BryceStevenWilley in [PR 704](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/704)
* Remove extra quote when formatting numbers by @BryceStevenWilley in [PR 716](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/716)
* Use skip undefined with instructions page; better handling of original_form if left blank; fix bug where addendum code would create blank output by @nonprofittechy in [PR 732](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/732)

### Cleanup
* Correct publish directory by @BryceStevenWilley in [PR 715](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/715)
* More types by @BryceStevenWilley in [PR 712](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/712)
* Make pike fields a dict instead, not same order by @BryceStevenWilley in [PR 724](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/724)
* Type cleanup by @BryceStevenWilley in [PR 725](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/725)
* Delete duplicate license by @BryceStevenWilley in [PR 737](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/737)
* Use SVG logo instead of PNG, improve and simplify path by @nonprofittechy in [PR 734](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/734)

## Version v1.7.0

### New

* Let someone auto-recognize form fields in a PDF by @nonprofittechy in [PR 599](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/599)
* Add fax_number and language suffixes, which are supported in AL > 2.11.0 by @nonprofittechy in [PR 606](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/606)
* Add better interview stats integration by @purplesky2016 in [PR 616](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/616)
* Automate multiple forms in one Weaver run by @nonprofittechy in [PR 646](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/646)

### Fixed

* fix-skip-button by @purplesky2016 in [PR 618](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/618)
* Fix 0th docx & Allow `manual_line_break` by @BryceStevenWilley in [PR 614](https://github.com/SuffolkLITLab/docassemble-ALWeaver/pull/614)

**Full Changelog**: https://github.com/SuffolkLITLab/docassemble-ALWeaver/compare/v1.6.3...v1.7.0

## Version v1.6.3

FormFyxer is back!

## Version v1.6.2

Revert FormFyxer, spacy models aren't installing correctly.

## Version v1.6.1

Bug fix:
Issue with I'm feeling lucky button

## Version v1.6.0

* Allow renaming fields in the automation process
* Integrate field normalizing function (automated renaming) from FormFyxer
* Rearrange fields with drag and drop
* sanitize input filenames
* preparation for improved testing process

## Version v1.5.1

Fix issue with "I'm feeling lucky" button

## Version v1.4.0

2021-11-03
* Add support for *plural* names for people in PDF files

## Version v1.3.0

2021-10-15:
* Handle overflow in addendum
* Multiple choice radio/checkbox fields
* DOCX validation

## Version v1.2.0

2021-09-09:
* Improved internationalization
* Simplified PDF checker


## Version v0.81

2021-04-14: Multiple fixes:
* Migrated to more flexible Mako template structure for generated
  interview blocks
* Package can be installed (for test purposes) after being
  generated
* Various refactors and code cleanup
* Simplified and improved generated code and order of blocks
* Added version number/date stamp to generated code


## Version v0.70

2021-03-09: Extensive improvements:
* Improvements to review screens
* Question/field editing and reordering
* Improvements to YAML structure
* Generate interstitial screens
* Refactoring and bug fixes


## Version v0.57

2021-02-09: Combine yes/no variables; more flexible handling of people variables and assistance with gathering varying numbers w/ less code

## Version v0.55

2021-01-29: Bug fixes; migration to AssemblyLine complete

## Version v0.54

2021-01-25: Bug fixes, start migration to [AssemblyLine](https://github.com/SuffolkLITLab/docassemble-AssemblyLine) dependency and away from MAVirtualCourt.
