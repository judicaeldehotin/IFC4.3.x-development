Element Filling
===============

Elements such as doors and windows may be placed inside openings of walls, slabs, or other elements.

```
concept {
    IfcElement_0:FillsVoids -> IfcRelFillsElement:RelatedBuildingElement
    IfcRelFillsElement:RelatingOpeningElement -> IfcOpeningElement
    IfcOpeningElement:VoidsElements -> IfcRelVoidsElement:RelatedOpeningElement
    IfcRelVoidsElement:RelatingBuildingElement -> IfcElement_1
    IfcRelVoidsElement:RelatingBuildingElement[binding="Type"]
}
```
