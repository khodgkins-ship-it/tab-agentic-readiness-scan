# Tableau Metadata API — Types, Enums & Filters
# Source: live GraphQL introspection (349 total types)

## Table of Contents
1. [Interfaces](#interfaces)  — shared field contracts
2. [Key Object Types](#key-object-types)  — most-queried types with unique fields
3. [Enums](#enums)
4. [Filter Inputs](#filter-inputs)  — filter: arguments for root queries
5. [Connection Types Index](#connection-types-index)  — all paginated types
6. Extended / less-common types: see `references/types-extended.md`

**Note on lineage fields**: upstream/downstream traversal fields follow the same
pattern across all types. Each type shows them as a compact comment line.
All have both a direct form `upstreamTables: [Table]` and a paginated
connection form `upstreamTablesConnection: DatabaseTablesConnection`.

## Interfaces

### AnalyticsField
  # Base GraphQL type for a field containing analytics metadata
  defaultFormat: String
  semanticRole: String
  aggregation: String
  aggregationParam: String
  directSheets: [Sheet]
  sheets: [Sheet]
  datasource: Datasource
  metricDefinitions: [MetricDefinition]
  derivedLensFields: [LensField]

### CanHaveLabels
  # A content item that can have labels.   *Available in Tableau Cloud March 2023 / Server 2023.1 and later.*
  id: ID!
  name: String
  luid: String!
  labels: [unknown]!

### Certifiable
  # A content item that can be certified
  id: ID!
  name: String
  luid: String!
  isCertified: Boolean!
  dataQualityCertifications: [unknown]!

### DataField
  # Base GraphQL type for a field containing data. Most types of Fields will implement this interface with exceptions like H
  dataCategory: FieldRoleCategory
  role: FieldRole
  dataType: FieldDataType
  directSheets: [Sheet]
  sheets: [Sheet]
  datasource: Datasource
  metricDefinitions: [MetricDefinition]
  derivedLensFields: [LensField]

### Database
  # A database containing tables
  id: ID!
  vizportalId: String!
  luid: String!
  name: String
  connectionType: String
  isEmbedded: Boolean
  description: String
  projectVizportalUrlId: String
  projectName: String
  contact: TableauUser
  isCertified: Boolean!
  isControlledPermissionsEnabled: Boolean
  isGrouped: Boolean
  hasActiveWarning: Boolean!
  dataQualityWarnings: [unknown]!
  dataQualityCertifications: [unknown]!
  labels: [unknown]!
  tags: [unknown]!
  tables: [DatabaseTable]

### Datasource
  # Root GraphQL type for embedded and published data sources  Data sources are a way to represent how Tableau Desktop and T
  id: ID!
  name: String
  hasUserReference: Boolean
  hasExtracts: Boolean
  containsUnsupportedCustomSql: Boolean
  extractLastRefreshTime: DateTime
  extractLastIncrementalUpdateTime: DateTime
  extractLastUpdateTime: DateTime
  fields: [unknown]!
  datasourceFilters: [unknown]!
  createdAt: DateTime
  updatedAt: DateTime
  lenses: [Lens]

### Field
  # Base GraphQL type for a field
  id: ID!
  name: String
  fullyQualifiedName: String
  description: String
  descriptionInherited: [InheritedStringResult]
  isHidden: Boolean
  folderName: String
  datasource: Datasource
  derivedLensFields: [LensField]
  metricDefinitions: [MetricDefinition]
  sheets: [Sheet]
  directSheets: [Sheet]

### FieldReferencingField
  # Base GraphQL type for a field that references another field. For example, a CalculatedField can reference a ColumnField 
  id: ID!
  fullyQualifiedName: String
  fields: [unknown]!
  directSheets: [Sheet]
  sheets: [Sheet]
  datasource: Datasource
  metricDefinitions: [MetricDefinition]
  derivedLensFields: [LensField]

### FlowInputField
  # A wrapper for an input field contained in a published flow.
  id: ID!
  name: String
  childFields: [unknown]!
  flow: Flow

### FlowOutputField
  # A wrapper for an output field contained in a published flow.
  id: ID!
  name: String
  parentFields: [unknown]!
  flow: [Flow]
  flowOutputStep: FlowOutputStep

### Label
  # A label that can be attached to assets.   *Available in Tableau Cloud March 2023 / Server 2023.1 and later.*
  id: ID!
  author: TableauUser
  authorDisplayName: String
  vizportalId: String!
  luid: String!
  isActive: Boolean!
  isElevated: Boolean!
  value: String!
  category: String!
  message: String
  createdAt: DateTime!
  updatedAt: DateTime!
  asset: CanHaveLabels

### Node
  # Inheritance target
  id: ID!

### Table
  # A table containing columns
  id: ID!
  name: String
  isEmbedded: Boolean
  description: String
  columns: [unknown]!

### Taggable
  # A content item that has a list of tags
  id: ID!
  name: String
  luid: String!
  tags: [unknown]!

### View
  # A view contained in a published workbook. Views can be sheets or dashboards.
  id: ID!
  name: String
  documentViewId: String
  luid: String!
  path: String
  createdAt: DateTime!
  updatedAt: DateTime!
  index: Int
  tags: [unknown]!
  workbook: Workbook

### Warnable
  # A content item that can have data quality warnings
  id: ID!
  name: String
  luid: String!
  hasActiveWarning: Boolean!
  dataQualityWarnings: [unknown]!

## Key Object Types

Fields unique to each type. Lineage traversals (upstream/downstream) shown as
compact comment — all have both direct and `*Connection` paginated forms.

### PublishedDatasource
  # implements: Datasource, Warnable, Certifiable, CanHaveLabels, Taggable
  id: ID!
  name: String
  hasUserReference: Boolean
  hasExtracts: Boolean
  containsUnsupportedCustomSql: Boolean
  extractLastRefreshTime: DateTime
  extractLastIncrementalUpdateTime: DateTime
  extractLastUpdateTime: DateTime
  luid: String!
  fields: [unknown]!
  datasourceFilters: [unknown]!
  parameters: [unknown]!
  site: TableauSite!
  projectVizportalUrlId: String
  projectName: String
  containerType: String!
  containerName: String
  owner: TableauUser!
  isCertified: Boolean!
  description: String
  hasActiveWarning: Boolean!
  dataQualityWarnings: [unknown]!
  dataQualityCertifications: [unknown]!
  labels: [unknown]!
  tags: [unknown]!
  uri: String
  vizportalId: String!
  vizportalUrlId: String!
  createdAt: DateTime
  updatedAt: DateTime
  lenses: [Lens]
  # upstream: upstreamDatabases, upstreamTables, upstreamFlows, upstreamDatasources, upstreamDataQualityWarnings, upstreamLabels, upstreamVirtualConnectionTables, upstreamVirtualConnections
  # downstream: downstreamTables, downstreamDatabases, downstreamVirtualConnectionTables, downstreamVirtualConnections, downstreamFlows, downstreamDatasources, downstreamLenses, downstreamSheets, downstreamDashboards, downstreamWorkbooks, downstreamMetrics, downstreamOwners, downstreamMetricDefinitions

### EmbeddedDatasource
  # implements: Datasource
  id: ID!
  name: String
  hasUserReference: Boolean
  hasExtracts: Boolean
  containsUnsupportedCustomSql: Boolean
  extractLastRefreshTime: DateTime
  extractLastIncrementalUpdateTime: DateTime
  extractLastUpdateTime: DateTime
  fields: [unknown]!
  datasourceFilters: [unknown]!
  parentPublishedDatasources: [unknown]!
  createdAt: DateTime
  updatedAt: DateTime
  lenses: [Lens]
  workbook: Workbook
  # upstream: upstreamTables, upstreamDatabases, upstreamFlows, upstreamDatasources, upstreamDataQualityWarnings, upstreamLabels
  # downstream: downstreamSheets, downstreamDashboards, downstreamWorkbooks, downstreamOwners, downstreamFlows

### DatabaseTable
  # implements: Table, Warnable, Certifiable, CanHaveLabels, Taggable
  id: ID!
  vizportalId: String!
  luid: String!
  name: String
  isEmbedded: Boolean
  tableType: TableType!
  schema: String
  fullName: String
  connectionType: String
  projectVizportalUrlId: String
  projectName: String
  description: String
  contact: TableauUser
  isCertified: Boolean!
  tags: [unknown]!
  database: Database
  columns: [unknown]!
  additionalDetails: TableAdditionalDetails
  hasActiveWarning: Boolean!
  dataQualityWarnings: [unknown]!
  dataQualityCertifications: [unknown]!
  labels: [unknown]!
  # upstream: upstreamDataQualityWarnings, upstreamLabels, upstreamDatabases, upstreamTables, upstreamVirtualConnections, upstreamVirtualConnectionTables, upstreamFlows, upstreamDatasources
  # downstream: downstreamDatabases, downstreamTables, downstreamVirtualConnectionTables, downstreamVirtualConnections, downstreamFlows, downstreamDatasources, downstreamLenses, downstreamSheets, downstreamDashboards, downstreamMetrics, downstreamWorkbooks, downstreamOwners, downstreamMetricDefinitions
  # referencedBy: referencedByQueries

### DatabaseServer
  # implements: Database, Warnable, Certifiable, CanHaveLabels, Taggable
  id: ID!
  vizportalId: String!
  luid: String!
  name: String
  connectionType: String
  extendedConnectionType: String
  isEmbedded: Boolean
  hostName: String
  port: Int
  description: String
  projectVizportalUrlId: String
  projectName: String
  contact: TableauUser
  isCertified: Boolean!
  isControlledPermissionsEnabled: Boolean
  isGrouped: Boolean
  hasActiveWarning: Boolean!
  service: String
  dataQualityWarnings: [unknown]!
  dataQualityCertifications: [unknown]!
  labels: [unknown]!
  tags: [unknown]!
  tables: [DatabaseTable]
  # upstream: upstreamDataQualityWarnings, upstreamLabels, upstreamDatabases, upstreamTables, upstreamVirtualConnections, upstreamVirtualConnectionTables, upstreamFlows, upstreamDatasources
  # downstream: downstreamDatabases, downstreamTables, downstreamVirtualConnections, downstreamVirtualConnectionTables, downstreamFlows, downstreamDatasources, downstreamLenses, downstreamWorkbooks, downstreamDashboards, downstreamSheets, downstreamMetrics, downstreamOwners, downstreamMetricDefinitions
  # referencedBy: referencedByQueries

### CustomSQLTable
  # implements: Table
  id: ID!
  name: String
  isUnsupportedCustomSql: Boolean
  isEmbedded: Boolean
  description: String
  query: String
  connectionType: String
  columns: [unknown]!
  tables: [unknown]!
  database: Database
  # upstream: upstreamDatabases, upstreamTables, upstreamVirtualConnections, upstreamVirtualConnectionTables, upstreamFlows, upstreamDatasources
  # downstream: downstreamDatabases, downstreamTables, downstreamVirtualConnectionTables, downstreamVirtualConnections, downstreamFlows, downstreamDatasources, downstreamLenses, downstreamWorkbooks, downstreamSheets, downstreamDashboards, downstreamMetrics, downstreamOwners

### Column
  # implements: Warnable, CanHaveLabels, Taggable, Node
  id: ID!
  vizportalId: String
  luid: String!
  name: String
  displayName: String
  description: String
  descriptionInherited: [InheritedStringResult]
  remoteType: RemoteType!
  isNullable: Boolean
  hasActiveWarning: Boolean!
  dataQualityWarnings: [unknown]!
  labels: [unknown]!
  tags: [unknown]!
  remoteColumn: Column
  table: Table
  # upstream: upstreamTables, upstreamVirtualConnectionTables, upstreamVirtualConnections, upstreamDatabases, upstreamFlows, upstreamDatasources, upstreamFields, upstreamColumns
  # downstream: downstreamColumns, downstreamTables, downstreamVirtualConnectionTables, downstreamVirtualConnections, downstreamDatabases, downstreamFlows, downstreamFields, downstreamDatasources, downstreamLenses, downstreamSheets, downstreamDashboards, downstreamWorkbooks, downstreamMetrics, downstreamOwners, downstreamMetricDefinitions
  # referencedBy: referencedByFlowColumnInputField, referencedByFlowColumnOutputField, referencedByRemoteColumn, referencedByFields

### Workbook
  # implements: Taggable
  id: ID!
  name: String
  luid: String!
  containsUnsupportedCustomSql: Boolean
  site: TableauSite!
  projectVizportalUrlId: String
  projectName: String
  projectLuid: String
  containerType: String!
  containerName: String
  owner: TableauUser!
  tags: [unknown]!
  views: [unknown]!
  sheets: [unknown]!
  dashboards: [unknown]!
  embeddedDatasources: [unknown]!
  parameters: [unknown]!
  description: String
  uri: String
  vizportalUrlId: String!
  createdAt: DateTime!
  updatedAt: DateTime!
  # upstream: upstreamDataQualityWarnings, upstreamLabels, upstreamDatabases, upstreamLenses, upstreamFlows, upstreamTables, upstreamVirtualConnectionTables, upstreamVirtualConnections, upstreamDatasources
  # downstream: downstreamMetrics, downstreamOwners

### Sheet
  # implements: View, Taggable
  id: ID!
  name: String
  documentViewId: String
  luid: String!
  path: String
  createdAt: DateTime!
  updatedAt: DateTime!
  index: Int
  tags: [unknown]!
  worksheetFields: [CalculatedField]
  datasourceFields: [Field]
  sheetFieldInstances: [Field]
  parentEmbeddedDatasources: [unknown]!
  workbook: Workbook
  containedInDashboards: [Dashboard]
  # upstream: upstreamDataQualityWarnings, upstreamLabels, upstreamDatabases, upstreamDatasources, upstreamTables, upstreamFields, upstreamFlows, upstreamColumns
  # referencedBy: referencedByMetrics

### Dashboard
  # implements: View, Taggable
  id: ID!
  name: String
  documentViewId: String
  luid: String!
  path: String
  createdAt: DateTime!
  updatedAt: DateTime!
  index: Int
  tags: [unknown]!
  sheets: [unknown]!
  askDataExtensions: [unknown]!
  workbook: Workbook
  # upstream: upstreamSheetFieldInstances, upstreamDataQualityWarnings, upstreamLabels, upstreamDatabases, upstreamDatasources, upstreamTables, upstreamFields, upstreamLenses, upstreamFlows, upstreamColumns
  # referencedBy: referencedByMetrics

### Flow
  # implements: Warnable, CanHaveLabels, Taggable
  id: ID!
  name: String
  uri: String
  vizportalUrlId: String!
  createdAt: DateTime
  updatedAt: DateTime
  site: TableauSite
  projectVizportalUrlId: String
  projectName: String
  personalSpaceUrlLink: String
  containerType: String!
  containerName: String
  owner: TableauUser
  inputFields: [unknown]!
  outputFields: [unknown]!
  outputSteps: [unknown]!
  description: String
  hasActiveWarning: Boolean!
  containsUnsupportedCustomSql: Boolean
  luid: String!
  tags: [unknown]!
  dataQualityWarnings: [unknown]!
  labels: [unknown]!
  nextDownstreamFlows: [unknown]!
  nextUpstreamFlows: [unknown]!
  # upstream: upstreamDataQualityWarnings, upstreamLabels, upstreamDatabases, upstreamTables, upstreamFlows, upstreamDatasources, upstreamLinkedFlows, upstreamVirtualConnectionTables, upstreamVirtualConnections
  # downstream: downstreamFlows, downstreamLinkedFlows, downstreamDatasources, downstreamLenses, downstreamDatabases, downstreamTables, downstreamWorkbooks, downstreamDashboards, downstreamSheets, downstreamMetrics, downstreamVirtualConnections, downstreamVirtualConnectionTables, downstreamOwners, downstreamMetricDefinitions

### FlowOutputStep
  id: ID!
  name: String
  stepId: String
  outputFields: [unknown]!
  flow: Flow

### VirtualConnection
  # implements: Certifiable, Warnable, CanHaveLabels, Taggable
  tables: [unknown]!
  id: ID!
  vizportalId: String!
  vizportalUrlId: String!
  uri: String
  luid: String!
  name: String
  createdAt: DateTime
  updatedAt: DateTime
  site: TableauSite!
  projectVizportalUrlId: String
  projectName: String
  containerType: String!
  containerName: String
  description: String
  owner: TableauUser!
  hasActiveWarning: Boolean!
  dataQualityWarnings: [unknown]!
  dataQualityCertifications: [unknown]!
  labels: [unknown]!
  isCertified: Boolean!
  tags: [unknown]!
  # upstream: upstreamDatabases, upstreamTables, upstreamVirtualConnectionTables, upstreamFlows, upstreamDatasources, upstreamDataQualityWarnings, upstreamLabels
  # downstream: downstreamFlows, downstreamWorkbooks, downstreamDatasources, downstreamLenses, downstreamSheets, downstreamDashboards, downstreamVirtualConnectionTables, downstreamMetrics, downstreamOwners, downstreamMetricDefinitions

### VirtualConnectionTable
  # implements: Table, Certifiable, Warnable, CanHaveLabels, Taggable
  vizportalId: String
  uri: String
  vizportalUrlId: String!
  luid: String!
  isExtracted: Boolean
  containsUnsupportedCustomSql: Boolean
  extractLastRefreshedAt: DateTime
  extractLastRefreshType: ExtractType
  id: ID!
  name: String
  isEmbedded: Boolean
  description: String
  owner: TableauUser!
  hasActiveWarning: Boolean!
  dataQualityWarnings: [unknown]!
  dataQualityCertifications: [unknown]!
  isCertified: Boolean!
  labels: [unknown]!
  tags: [unknown]!
  columns: [unknown]!
  # upstream: upstreamDatabases, upstreamTables, upstreamFlows, upstreamDatasources, upstreamVirtualConnectionTables, upstreamVirtualConnections, upstreamDataQualityWarnings, upstreamLabels
  # downstream: downstreamDatabases, downstreamTables, downstreamVirtualConnectionTables, downstreamVirtualConnections, downstreamFlows, downstreamDatasources, downstreamLenses, downstreamSheets, downstreamWorkbooks, downstreamDashboards, downstreamMetrics, downstreamOwners, downstreamMetricDefinitions

### ColumnField
  # implements: Field, DataField, AnalyticsField, Node
  id: ID!
  name: String
  fullyQualifiedName: String
  description: String
  descriptionInherited: [InheritedStringResult]
  isHidden: Boolean
  folderName: String
  dataCategory: FieldRoleCategory
  role: FieldRole
  dataType: FieldDataType
  defaultFormat: String
  semanticRole: String
  aggregation: String
  aggregationParam: String
  columns: [unknown]!
  datasource: Datasource
  derivedLensFields: [LensField]
  metricDefinitions: [MetricDefinition]
  sheets: [Sheet]
  directSheets: [Sheet]
  # upstream: upstreamTables, upstreamVirtualConnectionTables, upstreamVirtualConnections, upstreamDatabases, upstreamFlows, upstreamDatasources, upstreamFields, upstreamColumns
  # downstream: downstreamColumns, downstreamTables, downstreamVirtualConnectionTables, downstreamVirtualConnections, downstreamDatabases, downstreamFlows, downstreamFields, downstreamDatasources, downstreamLenses, downstreamSheets, downstreamDashboards, downstreamWorkbooks, downstreamMetrics, downstreamOwners, downstreamMetricDefinitions
  # referencedBy: referencedByFields, referencedByFlowFieldInputField, referencedByFlowFieldOutputField, referencedByFilters, referencedByBins, referencedByCalculations, referencedByCombinedFields, referencedByCombinedSets, referencedByRemoteFields, referencedByGroups, referencedBySets, referencedByHierarchies

### CalculatedField
  # implements: Field, DataField, AnalyticsField, FieldReferencingField, Node
  id: ID!
  name: String
  fullyQualifiedName: String
  description: String
  descriptionInherited: [InheritedStringResult]
  isHidden: Boolean
  folderName: String
  dataCategory: FieldRoleCategory
  role: FieldRole
  dataType: FieldDataType
  defaultFormat: String
  semanticRole: String
  aggregation: String
  aggregationParam: String
  formula: String
  isAutoGenerated: Boolean
  hasUserReference: Boolean
  fields: [unknown]!
  parameters: [unknown]!
  datasource: Datasource
  derivedLensFields: [LensField]
  metricDefinitions: [MetricDefinition]
  sheet: Sheet
  sheets: [Sheet]
  directSheets: [Sheet]
  # upstream: upstreamTables, upstreamVirtualConnectionTables, upstreamVirtualConnections, upstreamDatabases, upstreamFlows, upstreamDatasources, upstreamFields, upstreamColumns
  # downstream: downstreamColumns, downstreamTables, downstreamVirtualConnectionTables, downstreamVirtualConnections, downstreamDatabases, downstreamFlows, downstreamFields, downstreamDatasources, downstreamLenses, downstreamSheets, downstreamDashboards, downstreamWorkbooks, downstreamMetrics, downstreamOwners, downstreamMetricDefinitions
  # referencedBy: referencedByFields, referencedByFlowFieldInputField, referencedByFlowFieldOutputField, referencedByFilters, referencedByBins, referencedByCalculations, referencedByCombinedFields, referencedByCombinedSets, referencedByRemoteFields, referencedByGroups, referencedBySets, referencedByHierarchies

### DatasourceField
  # implements: Field, Node
  id: ID!
  name: String
  fullyQualifiedName: String
  description: String
  descriptionInherited: [InheritedStringResult]
  isHidden: Boolean
  folderName: String
  remoteField: Field
  datasource: Datasource
  derivedLensFields: [LensField]
  metricDefinitions: [MetricDefinition]
  sheets: [Sheet]
  directSheets: [Sheet]
  # upstream: upstreamTables, upstreamVirtualConnectionTables, upstreamVirtualConnections, upstreamDatabases, upstreamFlows, upstreamDatasources, upstreamFields, upstreamColumns
  # downstream: downstreamColumns, downstreamTables, downstreamVirtualConnectionTables, downstreamVirtualConnections, downstreamDatabases, downstreamFlows, downstreamFields, downstreamDatasources, downstreamLenses, downstreamSheets, downstreamDashboards, downstreamWorkbooks, downstreamMetrics, downstreamOwners, downstreamMetricDefinitions
  # referencedBy: referencedByFields, referencedByFlowFieldInputField, referencedByFlowFieldOutputField, referencedByFilters, referencedByBins, referencedByCalculations, referencedByCombinedFields, referencedByCombinedSets, referencedByRemoteFields, referencedByGroups, referencedBySets, referencedByHierarchies

### GroupField
  # implements: Field, DataField, FieldReferencingField, Node
  id: ID!
  name: String
  fullyQualifiedName: String
  description: String
  descriptionInherited: [InheritedStringResult]
  isHidden: Boolean
  folderName: String
  dataCategory: FieldRoleCategory
  role: FieldRole
  dataType: FieldDataType
  hasOther: Boolean
  fields: [unknown]!
  datasource: Datasource
  derivedLensFields: [LensField]
  metricDefinitions: [MetricDefinition]
  sheets: [Sheet]
  directSheets: [Sheet]
  # upstream: upstreamTables, upstreamVirtualConnectionTables, upstreamVirtualConnections, upstreamDatabases, upstreamFlows, upstreamDatasources, upstreamFields, upstreamColumns
  # downstream: downstreamColumns, downstreamTables, downstreamVirtualConnectionTables, downstreamVirtualConnections, downstreamDatabases, downstreamFlows, downstreamFields, downstreamDatasources, downstreamLenses, downstreamSheets, downstreamDashboards, downstreamWorkbooks, downstreamMetrics, downstreamOwners, downstreamMetricDefinitions
  # referencedBy: referencedByFields, referencedByFlowFieldInputField, referencedByFlowFieldOutputField, referencedByFilters, referencedByBins, referencedByCalculations, referencedByCombinedFields, referencedByCombinedSets, referencedByRemoteFields, referencedByGroups, referencedBySets, referencedByHierarchies

### BinField
  # implements: Field, DataField, FieldReferencingField, Node
  id: ID!
  name: String
  fullyQualifiedName: String
  description: String
  descriptionInherited: [InheritedStringResult]
  isHidden: Boolean
  folderName: String
  dataCategory: FieldRoleCategory
  role: FieldRole
  dataType: FieldDataType
  formula: String
  binSize: String
  fields: [unknown]!
  parameters: [unknown]!
  datasource: Datasource
  derivedLensFields: [LensField]
  metricDefinitions: [MetricDefinition]
  sheets: [Sheet]
  directSheets: [Sheet]
  # upstream: upstreamTables, upstreamVirtualConnectionTables, upstreamVirtualConnections, upstreamDatabases, upstreamFlows, upstreamDatasources, upstreamFields, upstreamColumns
  # downstream: downstreamColumns, downstreamTables, downstreamVirtualConnectionTables, downstreamVirtualConnections, downstreamDatabases, downstreamFlows, downstreamFields, downstreamDatasources, downstreamLenses, downstreamSheets, downstreamDashboards, downstreamWorkbooks, downstreamMetrics, downstreamOwners, downstreamMetricDefinitions
  # referencedBy: referencedByFields, referencedByFlowFieldInputField, referencedByFlowFieldOutputField, referencedByFilters, referencedByBins, referencedByCalculations, referencedByCombinedFields, referencedByCombinedSets, referencedByRemoteFields, referencedByGroups, referencedBySets, referencedByHierarchies

### SetField
  # implements: Field, FieldReferencingField, Node
  id: ID!
  name: String
  fullyQualifiedName: String
  description: String
  descriptionInherited: [InheritedStringResult]
  isHidden: Boolean
  folderName: String
  fields: [unknown]!
  parameters: [unknown]!
  datasource: Datasource
  derivedLensFields: [LensField]
  metricDefinitions: [MetricDefinition]
  sheets: [Sheet]
  directSheets: [Sheet]
  # upstream: upstreamTables, upstreamVirtualConnectionTables, upstreamVirtualConnections, upstreamDatabases, upstreamFlows, upstreamDatasources, upstreamFields, upstreamColumns
  # downstream: downstreamColumns, downstreamTables, downstreamVirtualConnectionTables, downstreamVirtualConnections, downstreamDatabases, downstreamFlows, downstreamFields, downstreamDatasources, downstreamLenses, downstreamSheets, downstreamDashboards, downstreamWorkbooks, downstreamMetrics, downstreamOwners, downstreamMetricDefinitions
  # referencedBy: referencedByFields, referencedByFlowFieldInputField, referencedByFlowFieldOutputField, referencedByFilters, referencedByBins, referencedByCalculations, referencedByCombinedFields, referencedByCombinedSets, referencedByRemoteFields, referencedByGroups, referencedBySets, referencedByHierarchies

### HierarchyField
  # implements: Field, FieldReferencingField, Node
  id: ID!
  name: String
  fullyQualifiedName: String
  description: String
  descriptionInherited: [InheritedStringResult]
  isHidden: Boolean
  folderName: String
  fields: [unknown]!
  datasource: Datasource
  derivedLensFields: [LensField]
  metricDefinitions: [MetricDefinition]
  sheets: [Sheet]
  directSheets: [Sheet]
  # upstream: upstreamTables, upstreamVirtualConnectionTables, upstreamVirtualConnections, upstreamDatabases, upstreamFlows, upstreamDatasources, upstreamFields, upstreamColumns
  # downstream: downstreamColumns, downstreamTables, downstreamVirtualConnectionTables, downstreamVirtualConnections, downstreamDatabases, downstreamFlows, downstreamFields, downstreamDatasources, downstreamLenses, downstreamSheets, downstreamDashboards, downstreamWorkbooks, downstreamMetrics, downstreamOwners, downstreamMetricDefinitions
  # referencedBy: referencedByFields, referencedByFlowFieldInputField, referencedByFlowFieldOutputField, referencedByFilters, referencedByBins, referencedByCalculations, referencedByCombinedFields, referencedByCombinedSets, referencedByRemoteFields, referencedByGroups, referencedBySets, referencedByHierarchies

### CombinedField
  # implements: Field, FieldReferencingField, Node
  id: ID!
  name: String
  fullyQualifiedName: String
  description: String
  descriptionInherited: [InheritedStringResult]
  isHidden: Boolean
  folderName: String
  fields: [unknown]!
  datasource: Datasource
  derivedLensFields: [LensField]
  metricDefinitions: [MetricDefinition]
  sheets: [Sheet]
  directSheets: [Sheet]
  # upstream: upstreamTables, upstreamVirtualConnectionTables, upstreamVirtualConnections, upstreamDatabases, upstreamFlows, upstreamDatasources, upstreamFields, upstreamColumns
  # downstream: downstreamColumns, downstreamTables, downstreamVirtualConnectionTables, downstreamVirtualConnections, downstreamDatabases, downstreamFlows, downstreamFields, downstreamDatasources, downstreamLenses, downstreamSheets, downstreamDashboards, downstreamWorkbooks, downstreamMetrics, downstreamOwners, downstreamMetricDefinitions
  # referencedBy: referencedByFields, referencedByFlowFieldInputField, referencedByFlowFieldOutputField, referencedByFilters, referencedByBins, referencedByCalculations, referencedByCombinedFields, referencedByCombinedSets, referencedByRemoteFields, referencedByGroups, referencedBySets, referencedByHierarchies

### Parameter
  id: ID!
  name: String
  parentName: String
  datasource: PublishedDatasource
  workbook: Workbook
  # referencedBy: referencedByBins, referencedByCalculations, referencedBySets

### TableauUser
  id: ID!
  uri: String!
  vizportalId: String!
  luid: String!
  username: String
  name: String
  domain: String
  email: String
  contactForDatabases: [Database]
  certifiedDatabases: [Database]
  authoredLabels: [Label]
  ownedLenses: [Lens]
  ownedFlows: [Flow]
  certifiedTables: [DatabaseTable]
  contactForTables: [DatabaseTable]
  ownedVirtualConnectionTables: [VirtualConnectionTable]
  ownedVirtualConnections: [VirtualConnection]
  ownedMetrics: [Metric]
  authoredDataQualityWarnings: [DataQualityWarning]
  authoredDataQualityCertifications: [DataQualityCertification]
  ownedDatasources: [PublishedDatasource]
  certifiedDatasources: [PublishedDatasource]
  ownedWorkbooks: [Workbook]

### Tag
  id: ID!
  name: String
  databases: [Database]
  assets: [Taggable]
  views: [View]
  flows: [Flow]
  databaseTables: [DatabaseTable]
  virtualConnectionTables: [VirtualConnectionTable]
  virtualConnections: [VirtualConnection]
  metrics: [Metric]
  columns: [Column]
  publishedDatasources: [PublishedDatasource]
  workbooks: [Workbook]

### Lens
  id: ID!
  name: String
  luid: String!
  site: TableauSite!
  fields: [unknown]!
  projectVizportalUrlId: String!
  vizportalUrlId: String!
  datasource: Datasource!
  owner: TableauUser!
  description: String
  createdAt: DateTime!
  updatedAt: DateTime!
  askDataExtensions: [AskDataExtension]
  # upstream: upstreamTables, upstreamDatabases, upstreamFields, upstreamFlows, upstreamVirtualConnectionTables, upstreamVirtualConnections, upstreamDatasources
  # downstream: downstreamDashboards, downstreamWorkbooks, downstreamMetrics, downstreamOwners

### MetricDefinition
  id: ID!
  name: String!
  luid: String!
  site: TableauSite!
  fields: [unknown]!
  # upstream: upstreamDatasources, upstreamLabels, upstreamFlows, upstreamDatabases, upstreamTables, upstreamVirtualConnectionTables, upstreamFields, upstreamFlowOutputFields, upstreamColumns, upstreamVirtualConnections

### DataQualityWarning
  # implements: Label
  id: ID!
  author: TableauUser
  authorDisplayName: String
  vizportalId: String!
  luid: String!
  isActive: Boolean!
  isElevated: Boolean!
  value: String!
  category: String!
  message: String
  createdAt: DateTime!
  updatedAt: DateTime!
  asset: CanHaveLabels

### DataQualityCertification
  # implements: Label
  id: ID!
  author: TableauUser
  authorDisplayName: String
  vizportalId: String!
  luid: String!
  isActive: Boolean!
  isElevated: Boolean!
  value: String!
  category: String!
  message: String
  createdAt: DateTime!
  updatedAt: DateTime!
  asset: CanHaveLabels

### DatasourceFilter
  id: ID!
  field: Field!
  datasource: Datasource

### InheritedStringResult
  assetId: String!
  attribute: String!
  value: String
  distance: Int
  edges: [unknown!]
  asset: Node

### CloudFile
  # implements: Database, Warnable, Certifiable, CanHaveLabels, Taggable
  id: ID!
  vizportalId: String!
  luid: String!
  name: String
  connectionType: String
  isEmbedded: Boolean
  provider: String
  fileExtension: String
  mimeType: String
  fileId: String
  requestUrl: String
  description: String
  projectVizportalUrlId: String
  projectName: String
  contact: TableauUser
  isCertified: Boolean!
  isControlledPermissionsEnabled: Boolean
  isGrouped: Boolean
  hasActiveWarning: Boolean!
  dataQualityWarnings: [unknown]!
  dataQualityCertifications: [unknown]!
  labels: [unknown]!
  tags: [unknown]!
  tables: [DatabaseTable]
  # upstream: upstreamDataQualityWarnings, upstreamLabels, upstreamDatabases, upstreamTables, upstreamVirtualConnections, upstreamVirtualConnectionTables, upstreamFlows, upstreamDatasources
  # downstream: downstreamDatabases, downstreamTables, downstreamVirtualConnections, downstreamVirtualConnectionTables, downstreamFlows, downstreamDatasources, downstreamLenses, downstreamWorkbooks, downstreamDashboards, downstreamSheets, downstreamMetrics, downstreamOwners, downstreamMetricDefinitions
  # referencedBy: referencedByQueries

### DataCloud
  # implements: Database, Warnable, Certifiable, CanHaveLabels, Taggable
  id: ID!
  vizportalId: String!
  luid: String!
  name: String
  connectionType: String
  isEmbedded: Boolean
  description: String
  projectVizportalUrlId: String
  projectName: String
  contact: TableauUser
  isCertified: Boolean!
  isControlledPermissionsEnabled: Boolean
  isGrouped: Boolean
  hasActiveWarning: Boolean!
  dataQualityWarnings: [unknown]!
  dataQualityCertifications: [unknown]!
  labels: [unknown]!
  tags: [unknown]!
  tables: [DatabaseTable]
  # upstream: upstreamDataQualityWarnings, upstreamLabels, upstreamDatabases, upstreamTables, upstreamVirtualConnections, upstreamVirtualConnectionTables, upstreamFlows, upstreamDatasources
  # downstream: downstreamDatabases, downstreamTables, downstreamVirtualConnections, downstreamVirtualConnectionTables, downstreamFlows, downstreamDatasources, downstreamLenses, downstreamWorkbooks, downstreamDashboards, downstreamSheets, downstreamMetrics, downstreamOwners, downstreamMetricDefinitions
  # referencedBy: referencedByQueries

## Enums

### AnalyticsFieldOrderField
  # Enum for fields that can be used for sorting
  ID

### AskDataExtensionOrderField
  # Enum for fields that can be used for sorting
  ID

### BinFieldOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_SHEETS_COUNT
  FIELDS_COUNT
  DATA_CATEGORY
  DATA_TYPE
  ID
  IS_HIDDEN
  NAME
  ROLE

### CalculatedFieldOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_SHEETS_COUNT
  FIELDS_COUNT
  DATA_CATEGORY
  DATA_TYPE
  ID
  IS_HIDDEN
  NAME
  ROLE

### CanHaveLabelsOrderField
  # Enum for fields that can be used for sorting
  ID
  LUID

### CertifiableOrderField
  # Enum for fields that can be used for sorting
  ID
  IS_CERTIFIED
  LUID

### CloudFileOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_DATASOURCES_COUNT
  DOWNSTREAM_VIRTUAL_CONNECTIONS_COUNT
  DOWNSTREAM_WORKBOOKS_COUNT
  CONNECTION_TYPE
  HAS_ACTIVE_WARNING
  ID
  IS_CERTIFIED
  IS_EMBEDDED
  LUID
  NAME
  PROJECT_NAME

### ColumnFieldOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_SHEETS_COUNT
  DATA_CATEGORY
  DATA_TYPE
  ID
  IS_HIDDEN
  NAME
  ROLE

### ColumnOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_SHEETS_COUNT
  DISPLAY_NAME
  HAS_ACTIVE_WARNING
  ID
  LUID
  NAME

### CombinedFieldOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_SHEETS_COUNT
  FIELDS_COUNT
  ID
  IS_HIDDEN
  NAME

### CombinedSetFieldOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_SHEETS_COUNT
  FIELDS_COUNT
  ID
  IS_HIDDEN
  NAME

### CustomSQLTableOrderField
  # Enum for fields that can be used for sorting
  COLUMNS_COUNT
  DOWNSTREAM_DASHBOARDS_COUNT
  DOWNSTREAM_DATASOURCES_COUNT
  DOWNSTREAM_WORKBOOKS_COUNT
  ID
  IS_UNSUPPORTED_CUSTOM_SQL
  NAME

### DashboardOrderField
  # Enum for fields that can be used for sorting
  DOCUMENT_VIEW_ID
  ID
  LUID
  NAME
  PATH

### DataCloudOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_DATASOURCES_COUNT
  DOWNSTREAM_VIRTUAL_CONNECTIONS_COUNT
  DOWNSTREAM_WORKBOOKS_COUNT
  CONNECTION_TYPE
  HAS_ACTIVE_WARNING
  ID
  IS_CERTIFIED
  IS_EMBEDDED
  LUID
  NAME
  PROJECT_NAME

### DataFieldOrderField
  # Enum for fields that can be used for sorting
  DATA_CATEGORY
  DATA_TYPE
  ID
  ROLE

### DataQualityCertificationOrderField
  # Enum for fields that can be used for sorting
  CATEGORY
  ID
  IS_ACTIVE
  IS_ELEVATED
  LUID
  VALUE

### DataQualityWarningOrderField
  # Enum for fields that can be used for sorting
  CATEGORY
  ID
  IS_ACTIVE
  IS_ELEVATED
  IS_SEVERE
  LUID
  VALUE
  WARNING_TYPE

### DatabaseOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_DATASOURCES_COUNT
  DOWNSTREAM_VIRTUAL_CONNECTIONS_COUNT
  DOWNSTREAM_WORKBOOKS_COUNT
  CONNECTION_TYPE
  HAS_ACTIVE_WARNING
  ID
  IS_CERTIFIED
  IS_EMBEDDED
  LUID
  NAME
  PROJECT_NAME

### DatabaseServerOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_DATASOURCES_COUNT
  DOWNSTREAM_VIRTUAL_CONNECTIONS_COUNT
  DOWNSTREAM_WORKBOOKS_COUNT
  CONNECTION_TYPE
  HAS_ACTIVE_WARNING
  HOST_NAME
  ID
  IS_CERTIFIED
  IS_EMBEDDED
  LUID
  NAME
  PROJECT_NAME

### DatabaseTableOrderField
  # Enum for fields that can be used for sorting
  COLUMNS_COUNT
  DOWNSTREAM_DASHBOARDS_COUNT
  DOWNSTREAM_DATASOURCES_COUNT
  DOWNSTREAM_VIRTUAL_CONNECTIONS_COUNT
  DOWNSTREAM_WORKBOOKS_COUNT
  CONNECTION_TYPE
  FULL_NAME
  HAS_ACTIVE_WARNING
  ID
  IS_CERTIFIED
  IS_EMBEDDED
  LUID
  NAME
  PROJECT_NAME
  SCHEMA

### DatasourceFieldOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_SHEETS_COUNT
  ID
  IS_HIDDEN
  NAME

### DatasourceFilterOrderField
  # Enum for fields that can be used for sorting
  ID

### DatasourceOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_OWNERS_COUNT
  DOWNSTREAM_WORKBOOKS_COUNT
  FIELDS_COUNT
  CONTAINS_UNSUPPORTED_CUSTOM_SQL
  ID
  NAME

### EmbeddedDatasourceOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_OWNERS_COUNT
  DOWNSTREAM_WORKBOOKS_COUNT
  FIELDS_COUNT
  CONTAINS_UNSUPPORTED_CUSTOM_SQL
  ID
  NAME

### ExtractType
  # Possible types of extract
  INCREMENTAL
  FULL

### FieldDataType
  # Possible data types for a field.
  INTEGER
  REAL
  STRING
  DATETIME
  DATE
  TUPLE
  SPATIAL
  BOOLEAN
  TABLE
  UNKNOWN

### FieldOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_SHEETS_COUNT
  ID
  IS_HIDDEN
  NAME

### FieldReferencingFieldOrderField
  # Enum for fields that can be used for sorting
  FIELDS_COUNT
  ID

### FieldRole
  # Possible roles of a field.
  DIMENSION
  MEASURE
  UNKNOWN

### FieldRoleCategory
  # Possible categories of a field role.
  QUANTITATIVE
  NOMINAL
  ORDINAL
  UNKNOWN

### FileOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_DATASOURCES_COUNT
  DOWNSTREAM_VIRTUAL_CONNECTIONS_COUNT
  DOWNSTREAM_WORKBOOKS_COUNT
  CONNECTION_TYPE
  HAS_ACTIVE_WARNING
  ID
  IS_CERTIFIED
  IS_EMBEDDED
  LUID
  NAME
  PROJECT_NAME

### FlowColumnInputFieldOrderField
  # Enum for fields that can be used for sorting
  ID
  NAME

### FlowColumnOutputFieldOrderField
  # Enum for fields that can be used for sorting
  ID
  NAME

### FlowFieldInputFieldOrderField
  # Enum for fields that can be used for sorting
  ID
  NAME

### FlowFieldOutputFieldOrderField
  # Enum for fields that can be used for sorting
  ID
  NAME

### FlowInputFieldOrderField
  # Enum for fields that can be used for sorting
  ID
  NAME

### FlowOrderField
  # Enum for fields that can be used for sorting
  CONTAINER_NAME
  CONTAINS_UNSUPPORTED_CUSTOM_SQL
  HAS_ACTIVE_WARNING
  ID
  LUID
  NAME
  PROJECT_NAME
  VIZPORTAL_URL_ID

### FlowOutputFieldOrderField
  # Enum for fields that can be used for sorting
  ID
  NAME

### FlowOutputStepOrderField
  # Enum for fields that can be used for sorting
  ID
  NAME

### GenericLabelOrderField
  # Enum for fields that can be used for sorting
  CATEGORY
  ID
  IS_ACTIVE
  IS_ELEVATED
  LUID
  VALUE

### GroupFieldOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_SHEETS_COUNT
  FIELDS_COUNT
  DATA_CATEGORY
  DATA_TYPE
  ID
  IS_HIDDEN
  NAME
  ROLE

### HierarchyFieldOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_SHEETS_COUNT
  FIELDS_COUNT
  ID
  IS_HIDDEN
  NAME

### InheritanceType
  # Method of selecting the objects (i.e., inheritance sources) to inherit from
  FIRST

### LabelOrderField
  # Enum for fields that can be used for sorting
  CATEGORY
  ID
  IS_ACTIVE
  IS_ELEVATED
  LUID
  VALUE

### LensFieldOrderField
  # Enum for fields that can be used for sorting
  ID
  NAME

### LensOrderField
  # Enum for fields that can be used for sorting
  FIELDS_COUNT
  OWNER_COUNT
  ID
  LUID
  NAME
  VIZPORTAL_URL_ID

### LinkedFlowOrderField
  # Enum for fields that can be used for sorting
  ID

### MetricDefinitionOrderField
  # Enum for fields that can be used for sorting
  FIELDS_COUNT
  ID
  LUID
  NAME

### MetricOrderField
  # Enum for fields that can be used for sorting
  OWNER_COUNT
  CONTAINER_NAME
  ID
  LUID
  NAME
  PROJECT_NAME
  VIZPORTAL_URL_ID

### NodeOrderField
  # Enum for fields that can be used for sorting
  ID

### OrderDirection
  # General object for sorting
  ASC
  DESC

### ParameterOrderField
  # Enum for fields that can be used for sorting
  ID
  NAME
  PARENT_NAME

### PermissionMode
  # Enum of the different ways to apply permissions.
  OBFUSCATE_RESULTS
  FILTER_RESULTS

### PublishedDatasourceOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_OWNERS_COUNT
  DOWNSTREAM_SHEETS_COUNT
  DOWNSTREAM_WORKBOOKS_COUNT
  FIELDS_COUNT
  OWNER_COUNT
  CONTAINER_NAME
  CONTAINS_UNSUPPORTED_CUSTOM_SQL
  HAS_ACTIVE_WARNING
  ID
  IS_CERTIFIED
  LUID
  NAME
  PROJECT_NAME
  VIZPORTAL_URL_ID

### RemoteType
  # Possible types of remote types  Types correspond to OLEDB types here: https://referencesource.micros
  EMPTY
  NULL
  I2
  I4
  R4
  R8
  CY
  DATE
  BSTR
  IDISPATCH
  ERROR
  BOOL
  VARIANT
  IUNKNOWN
  DECIMAL
  UI1
  ARRAY
  BYREF
  I1
  UI2
  UI4
  I8
  UI8
  GUID
  VECTOR
  FILETIME
  RESERVED
  BYTES
  STR
  WSTR
  NUMERIC
  UDT
  DBDATE
  DBTIME
  DBTIMESTAMP
  HCHAPTER
  PROPVARIANT
  VARNUMERIC
  WDC_INT
  WDC_FLOAT
  WDC_STRING
  WDC_DATETIME
  WDC_BOOL
  WDC_DATE
  WDC_GEOMETRY

### SetFieldOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_SHEETS_COUNT
  FIELDS_COUNT
  ID
  IS_HIDDEN
  NAME

### SheetOrderField
  # Enum for fields that can be used for sorting
  DATASOURCE_FIELDS_COUNT
  SHEET_FIELD_INSTANCES_COUNT
  WORKSHEET_FIELDS_COUNT
  DOCUMENT_VIEW_ID
  ID
  LUID
  NAME
  PATH

### TableAdditionalDetailsOrderField
  # Enum for fields that can be used for sorting
  ID

### TableOrderField
  # Enum for fields that can be used for sorting
  COLUMNS_COUNT
  DOWNSTREAM_DASHBOARDS_COUNT
  DOWNSTREAM_DATASOURCES_COUNT
  DOWNSTREAM_WORKBOOKS_COUNT
  ID
  NAME

### TableType
  # Possible types of table.    TableType is DATABASETABLE unless the object is a Salesforce Data Cloud 
  DATABASETABLE
  DATAMODEL
  DATALAKE
  CALCULATEDINSIGHT

### TableauSiteOrderField
  # Enum for fields that can be used for sorting
  ID
  LUID
  NAME

### TableauUserOrderField
  # Enum for fields that can be used for sorting
  DOMAIN
  EMAIL
  ID
  LUID
  NAME
  USERNAME

### TagOrderField
  # Enum for fields that can be used for sorting
  ID
  NAME

### TaggableOrderField
  # Enum for fields that can be used for sorting
  ID
  LUID

### ViewOrderField
  # Enum for fields that can be used for sorting
  DOCUMENT_VIEW_ID
  ID
  LUID
  NAME
  PATH

### VirtualConnectionOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_DATASOURCES_COUNT
  DOWNSTREAM_WORKBOOKS_COUNT
  OWNER_COUNT
  CONNECTION_TYPE
  CONTAINER_NAME
  HAS_ACTIVE_WARNING
  ID
  IS_CERTIFIED
  LUID
  NAME
  PROJECT_NAME
  VIZPORTAL_URL_ID

### VirtualConnectionTableOrderField
  # Enum for fields that can be used for sorting
  COLUMNS_COUNT
  DOWNSTREAM_DASHBOARDS_COUNT
  DOWNSTREAM_DATASOURCES_COUNT
  DOWNSTREAM_WORKBOOKS_COUNT
  OWNER_COUNT
  CONTAINS_UNSUPPORTED_CUSTOM_SQL
  EXTRACT_LAST_REFRESH_TYPE
  EXTRACT_LAST_REFRESHED_AT
  HAS_ACTIVE_WARNING
  ID
  IS_CERTIFIED
  IS_EXTRACTED
  LUID
  NAME
  VIZPORTAL_URL_ID

### WarnableOrderField
  # Enum for fields that can be used for sorting
  HAS_ACTIVE_WARNING
  ID
  LUID

### WebDataConnectorOrderField
  # Enum for fields that can be used for sorting
  DOWNSTREAM_DATASOURCES_COUNT
  DOWNSTREAM_VIRTUAL_CONNECTIONS_COUNT
  DOWNSTREAM_WORKBOOKS_COUNT
  CONNECTION_TYPE
  HAS_ACTIVE_WARNING
  ID
  IS_CERTIFIED
  IS_EMBEDDED
  LUID
  NAME
  PROJECT_NAME

### WorkbookOrderField
  # Enum for fields that can be used for sorting
  DASHBOARDS_COUNT
  EMBEDDED_DATASOURCES_COUNT
  OWNER_COUNT
  SHEETS_COUNT
  VIEWS_COUNT
  CONTAINER_NAME
  CONTAINS_UNSUPPORTED_CUSTOM_SQL
  ID
  LUID
  NAME
  PROJECT_LUID
  PROJECT_NAME
  VIZPORTAL_URL_ID

## Filter Inputs

Pass as `filter:` argument. All fields are optional and ANDed together.

### AnalyticsField_Filter
  id: ID
  idWithin: [unknown]

### AskDataExtension_Filter
  id: ID
  idWithin: [unknown]

### AskDataExtension_Required_Filter
  id: ID
  idWithin: [unknown]

### BinField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isHidden: Boolean
  isHiddenWithin: [unknown]
  text: String

### BinField_Required_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### CalculatedField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isHidden: Boolean
  isHiddenWithin: [unknown]
  text: String

### CalculatedField_Required_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### CanHaveLabels_Filter
  luid: String
  luidWithin: [unknown]
  id: ID
  idWithin: [unknown]

### Certifiable_Filter
  luid: String
  luidWithin: [unknown]
  isCertified: Boolean
  isCertifiedWithin: [unknown]
  id: ID
  idWithin: [unknown]

### CloudFile_Filter
  hasActiveWarning: Boolean
  hasActiveWarningWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  isCertified: Boolean
  isCertifiedWithin: [unknown]
  name: String
  nameWithin: [unknown]
  isEmbedded: Boolean
  isEmbeddedWithin: [unknown]
  id: ID
  idWithin: [unknown]
  projectName: String
  projectNameWithin: [unknown]
  connectionType: String
  connectionTypeWithin: [unknown]
  text: String

### ColumnField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isHidden: Boolean
  isHiddenWithin: [unknown]
  text: String

### ColumnField_Required_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### Column_Filter
  hasActiveWarning: Boolean
  hasActiveWarningWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  displayName: String
  displayNameWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### Column_Required_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### CombinedField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isHidden: Boolean
  isHiddenWithin: [unknown]
  text: String

### CombinedField_Required_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### CombinedSetField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isHidden: Boolean
  isHiddenWithin: [unknown]
  text: String

### CombinedSetField_Required_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### CustomSQLTable_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isUnsupportedCustomSql: Boolean
  isUnsupportedCustomSqlWithin: [unknown]
  text: String

### Dashboard_Filter
  path: String
  pathWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  documentViewId: String
  documentViewIdWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### DataCloud_Filter
  hasActiveWarning: Boolean
  hasActiveWarningWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  isCertified: Boolean
  isCertifiedWithin: [unknown]
  name: String
  nameWithin: [unknown]
  isEmbedded: Boolean
  isEmbeddedWithin: [unknown]
  id: ID
  idWithin: [unknown]
  projectName: String
  projectNameWithin: [unknown]
  connectionType: String
  connectionTypeWithin: [unknown]
  text: String

### DataField_Filter
  id: ID
  idWithin: [unknown]

### DataQualityCertification_Filter
  isElevated: Boolean
  isElevatedWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isActive: Boolean
  isActiveWithin: [unknown]
  category: String
  categoryWithin: [unknown]
  value: String
  valueWithin: [unknown]

### DataQualityWarning_Filter
  isElevated: Boolean
  isElevatedWithin: [unknown]
  warningType: String
  warningTypeWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isActive: Boolean
  isActiveWithin: [unknown]
  category: String
  categoryWithin: [unknown]
  value: String
  valueWithin: [unknown]
  isSevere: Boolean
  isSevereWithin: [unknown]

### DatabaseServer_Filter
  hostName: String
  hostNameWithin: [unknown]
  hasActiveWarning: Boolean
  hasActiveWarningWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  isCertified: Boolean
  isCertifiedWithin: [unknown]
  name: String
  nameWithin: [unknown]
  isEmbedded: Boolean
  isEmbeddedWithin: [unknown]
  id: ID
  idWithin: [unknown]
  projectName: String
  projectNameWithin: [unknown]
  connectionType: String
  connectionTypeWithin: [unknown]
  text: String

### DatabaseTable_Filter
  schema: String
  schemaWithin: [unknown]
  hasActiveWarning: Boolean
  hasActiveWarningWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  isCertified: Boolean
  isCertifiedWithin: [unknown]
  name: String
  nameWithin: [unknown]
  fullName: String
  fullNameWithin: [unknown]
  isEmbedded: Boolean
  isEmbeddedWithin: [unknown]
  id: ID
  idWithin: [unknown]
  projectName: String
  projectNameWithin: [unknown]
  connectionType: String
  connectionTypeWithin: [unknown]
  text: String

### Database_Filter
  hasActiveWarning: Boolean
  hasActiveWarningWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  isCertified: Boolean
  isCertifiedWithin: [unknown]
  name: String
  nameWithin: [unknown]
  isEmbedded: Boolean
  isEmbeddedWithin: [unknown]
  id: ID
  idWithin: [unknown]
  projectName: String
  projectNameWithin: [unknown]
  connectionType: String
  connectionTypeWithin: [unknown]
  text: String

### DatasourceField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isHidden: Boolean
  isHiddenWithin: [unknown]
  text: String

### DatasourceField_Required_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### DatasourceFilter_Filter
  id: ID
  idWithin: [unknown]

### Datasource_Filter
  containsUnsupportedCustomSql: Boolean
  containsUnsupportedCustomSqlWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### EmbeddedDatasource_Filter
  containsUnsupportedCustomSql: Boolean
  containsUnsupportedCustomSqlWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### ExtractType_Filter
  id: ID
  idWithin: [unknown]

### FieldDataType_Filter
  id: ID
  idWithin: [unknown]

### FieldReferencingField_Filter
  id: ID
  idWithin: [unknown]

### FieldRoleCategory_Filter
  id: ID
  idWithin: [unknown]

### FieldRole_Filter
  id: ID
  idWithin: [unknown]

### Field_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isHidden: Boolean
  isHiddenWithin: [unknown]
  text: String

### Field_Required_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### File_Filter
  hasActiveWarning: Boolean
  hasActiveWarningWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  isCertified: Boolean
  isCertifiedWithin: [unknown]
  name: String
  nameWithin: [unknown]
  isEmbedded: Boolean
  isEmbeddedWithin: [unknown]
  id: ID
  idWithin: [unknown]
  projectName: String
  projectNameWithin: [unknown]
  connectionType: String
  connectionTypeWithin: [unknown]
  text: String

### FlowColumnInputField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### FlowColumnOutputField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### FlowFieldInputField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### FlowFieldOutputField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### FlowInputField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### FlowOutputField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### FlowOutputStep_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### Flow_Filter
  containsUnsupportedCustomSql: Boolean
  containsUnsupportedCustomSqlWithin: [unknown]
  vizportalUrlId: String
  vizportalUrlIdWithin: [unknown]
  hasActiveWarning: Boolean
  hasActiveWarningWithin: [unknown]
  containerName: String
  containerNameWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  projectName: String
  projectNameWithin: [unknown]

### GenericLabel_Filter
  isElevated: Boolean
  isElevatedWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isActive: Boolean
  isActiveWithin: [unknown]
  category: String
  # IMPORTANT: built-in category values are ALL UPPERCASE: "SENSITIVITY", "WARNING", "CERTIFICATION"
  # category filter is case-sensitive — "Sensitivity" returns 0, "SENSITIVITY" returns correct count
  categoryWithin: [unknown]
  value: String
  valueWithin: [unknown]

### GroupField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isHidden: Boolean
  isHiddenWithin: [unknown]
  text: String

### GroupField_Required_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### HierarchyField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isHidden: Boolean
  isHiddenWithin: [unknown]
  text: String

### HierarchyField_Required_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### Label_Filter
  isElevated: Boolean
  isElevatedWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isActive: Boolean
  isActiveWithin: [unknown]
  category: String
  categoryWithin: [unknown]
  value: String
  valueWithin: [unknown]

### LensField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### LensField_Required_Filter
  id: ID
  idWithin: [unknown]

### Lens_Filter
  vizportalUrlId: String
  vizportalUrlIdWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### LinkedFlow_Filter
  id: ID
  idWithin: [unknown]

### MetricDefinition_Filter
  luid: String
  luidWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### Metric_Filter
  vizportalUrlId: String
  vizportalUrlIdWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  containerName: String
  containerNameWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  projectName: String
  projectNameWithin: [unknown]

### Node_Filter
  id: ID
  idWithin: [unknown]

### Parameter_Filter
  parentName: String
  parentNameWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### PublishedDatasource_Filter
  containsUnsupportedCustomSql: Boolean
  containsUnsupportedCustomSqlWithin: [unknown]
  hasActiveWarning: Boolean
  hasActiveWarningWithin: [unknown]
  vizportalUrlId: String
  vizportalUrlIdWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  containerName: String
  containerNameWithin: [unknown]
  isCertified: Boolean
  isCertifiedWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  projectName: String
  projectNameWithin: [unknown]

### RemoteType_Filter
  id: ID
  idWithin: [unknown]

### SetField_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isHidden: Boolean
  isHiddenWithin: [unknown]
  text: String

### SetField_Required_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### Sheet_Filter
  path: String
  pathWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  documentViewId: String
  documentViewIdWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### TableAdditionalDetails_Filter
  id: ID
  idWithin: [unknown]

### TableType_Filter
  id: ID
  idWithin: [unknown]

### Table_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  text: String

### TableauSite_Filter
  luid: String
  luidWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### TableauUser_Filter
  luid: String
  luidWithin: [unknown]
  domain: String
  domainWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  email: String
  emailWithin: [unknown]
  username: String
  usernameWithin: [unknown]

### Tag_Filter
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  text: String

### Taggable_Filter
  luid: String
  luidWithin: [unknown]
  id: ID
  idWithin: [unknown]

### View_Filter
  path: String
  pathWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  documentViewId: String
  documentViewIdWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]

### VirtualConnectionTable_Filter
  containsUnsupportedCustomSql: Boolean
  containsUnsupportedCustomSqlWithin: [unknown]
  vizportalUrlId: String
  vizportalUrlIdWithin: [unknown]
  hasActiveWarning: Boolean
  hasActiveWarningWithin: [unknown]
  extractLastRefreshedAt: DateTime
  extractLastRefreshedAtWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  isCertified: Boolean
  isCertifiedWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  isExtracted: Boolean
  isExtractedWithin: [unknown]

### VirtualConnection_Filter
  vizportalUrlId: String
  vizportalUrlIdWithin: [unknown]
  hasActiveWarning: Boolean
  hasActiveWarningWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  containerName: String
  containerNameWithin: [unknown]
  isCertified: Boolean
  isCertifiedWithin: [unknown]
  name: String
  nameWithin: [unknown]
  id: ID
  idWithin: [unknown]
  projectName: String
  projectNameWithin: [unknown]
  connectionType: String
  connectionTypeWithin: [unknown]

### Warnable_Filter
  hasActiveWarning: Boolean
  hasActiveWarningWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  id: ID
  idWithin: [unknown]

### WebDataConnector_Filter
  hasActiveWarning: Boolean
  hasActiveWarningWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  isCertified: Boolean
  isCertifiedWithin: [unknown]
  name: String
  nameWithin: [unknown]
  isEmbedded: Boolean
  isEmbeddedWithin: [unknown]
  id: ID
  idWithin: [unknown]
  projectName: String
  projectNameWithin: [unknown]
  connectionType: String
  connectionTypeWithin: [unknown]
  text: String

### Workbook_Filter
  containsUnsupportedCustomSql: Boolean
  containsUnsupportedCustomSqlWithin: [unknown]
  vizportalUrlId: String
  vizportalUrlIdWithin: [unknown]
  luid: String
  luidWithin: [unknown]
  containerName: String
  containerNameWithin: [unknown]
  name: String
  nameWithin: [unknown]
  projectLuid: String
  projectLuidWithin: [unknown]
  id: ID
  idWithin: [unknown]
  projectName: String
  projectNameWithin: [unknown]

## Connection Types Index

All paginated connection types. Always include `pageInfo { hasNextPage endCursor }` and `nodes { ... }`.

  AnalyticsFieldsConnection
  AskDataExtensionsConnection
  BinFieldsConnection
  CalculatedFieldsConnection
  CanHaveLabelsesConnection
  CertifiablesConnection
  CloudFilesConnection
  ColumnFieldsConnection
  ColumnsConnection
  CombinedFieldsConnection
  CombinedSetFieldsConnection
  CustomSQLTablesConnection
  DashboardsConnection
  DataCloudsConnection
  DataFieldsConnection
  DataQualityCertificationsConnection
  DataQualityWarningsConnection
  DatabaseServersConnection
  DatabaseTablesConnection
  DatabasesConnection
  DatasourceFieldsConnection
  DatasourceFiltersConnection
  DatasourcesConnection
  EmbeddedDatasourcesConnection
  FieldReferencingFieldsConnection
  FieldsConnection
  FilesConnection
  FlowColumnInputFieldsConnection
  FlowColumnOutputFieldsConnection
  FlowFieldInputFieldsConnection
  FlowFieldOutputFieldsConnection
  FlowInputFieldsConnection
  FlowOutputFieldsConnection
  FlowOutputStepsConnection
  FlowsConnection
  GenericLabelsConnection
  GroupFieldsConnection
  HierarchyFieldsConnection
  LabelsConnection
  LensFieldsConnection
  LensesConnection
  LinkedFlowsConnection
  MetricDefinitionsConnection
  MetricsConnection
  NodesConnection
  ParametersConnection
  PublishedDatasourcesConnection
  SetFieldsConnection
  SheetsConnection
  TableAdditionalDetailsesConnection
  TableauSitesConnection
  TableauUsersConnection
  TablesConnection
  TaggablesConnection
  TagsConnection
  ViewsConnection
  VirtualConnection
  VirtualConnectionTablesConnection
  VirtualConnectionsConnection
  WarnablesConnection
  WebDataConnectorsConnection
  WorkbooksConnection