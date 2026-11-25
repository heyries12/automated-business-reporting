const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const workflowPath = path.join(root, 'workflows', 'automated-business-reporting.json');
const csvPath = path.join(root, 'google-sheets-template.csv');
const workflow = JSON.parse(fs.readFileSync(workflowPath, 'utf8'));
const nodesByName = new Map(workflow.nodes.map((node) => [node.name, node]));

assert.equal(nodesByName.size, workflow.nodes.length, 'Node names must be unique');
assert.equal(workflow.active, false, 'Imported workflow must be inactive');
assert.equal(workflow.settings.timezone, 'UTC');
assert.equal(nodesByName.get('Daily Schedule').parameters.rule.interval[0].expression, '0 8 * * *');

for (const [source, connectionTypes] of Object.entries(workflow.connections)) {
  assert(nodesByName.has(source), `Unknown connection source: ${source}`);
  for (const outputs of Object.values(connectionTypes)) {
    for (const links of outputs) {
      for (const link of links) {
        assert(nodesByName.has(link.node), `Unknown connection target: ${link.node}`);
      }
    }
  }
}

const expectedEdges = [
  ['Daily Schedule', 0, 'Build Daily Period'],
  ['Build Daily Period', 0, 'Generate Report'],
  ['Generate Report', 0, 'Validate Report'],
  ['Validate Report', 0, 'Find Existing Report'],
  ['Find Existing Report', 0, 'Already Delivered?'],
  ['Already Delivered?', 1, 'Build Generated Row'],
  ['Build Generated Row', 0, 'Log Generated Report'],
  ['Log Generated Report', 0, 'Send Report Email'],
  ['Send Report Email', 0, 'Build Delivered Row'],
  ['Build Delivered Row', 0, 'Mark Report Delivered'],
];
for (const [source, outputIndex, target] of expectedEdges) {
  const links = workflow.connections[source].main[outputIndex];
  assert.equal(links.length, 1, `${source} must have one link on output ${outputIndex}`);
  assert.equal(links[0].node, target);
}

const csvHeaders = fs.readFileSync(csvPath, 'utf8').trim().split(',');
for (const name of ['Log Generated Report', 'Mark Report Delivered']) {
  const node = nodesByName.get(name);
  assert.deepEqual(node.parameters.columns.matchingColumns, ['report_key']);
  assert.deepEqual(
    node.parameters.columns.schema.map((column) => column.id),
    csvHeaders,
    `${name} schema must match the CSV`,
  );
  assert.equal(node.parameters.options.cellFormat, 'RAW');
  assert.equal(node.parameters.options.useAppend, false);
}
const lookup = nodesByName.get('Find Existing Report');
assert.equal(lookup.parameters.operation, 'read');
assert.equal(lookup.alwaysOutputData, true);
assert.match(lookup.parameters.filtersUI.values[0].lookupValue, /report_key/);

const buildPeriod = new Function(nodesByName.get('Build Daily Period').parameters.jsCode);
const periodItems = buildPeriod();
assert.equal(periodItems.length, 1);
assert.equal(
  new Date(periodItems[0].json.period_end) - new Date(periodItems[0].json.period_start),
  24 * 60 * 60 * 1000,
);
assert.match(periodItems[0].json.recipient_email, /REPLACE_WITH_REPORT_RECIPIENT/);

const sheetRow = Object.fromEntries(csvHeaders.map((header) => [header, '']));
Object.assign(sheetRow, {
  report_key: 'report-key-1',
  total_revenue: 1250.5,
  total_transactions: 12,
  completed_transactions: 10,
  average_order_value: 125.05,
  unique_customers: 9,
  delivery_status: 'generated',
});
const report = {
  report_key: 'report-key-1',
  email_subject: 'Daily Business Report',
  email_html: '<html><body>Report</body></html>',
  summary_mode: 'ai',
  sheet_row: sheetRow,
};

const validate = new Function('$json', nodesByName.get('Validate Report').parameters.jsCode);
assert.deepEqual(validate(report), { json: report });

const buildGenerated = new Function(
  '$json',
  '$',
  nodesByName.get('Build Generated Row').parameters.jsCode,
);
const nodeLookup = (name) => {
  assert.equal(name, 'Validate Report');
  return { first: () => ({ json: report }) };
};
const generated = buildGenerated({}, nodeLookup);
assert.equal(generated.json.delivery_status, 'generated');
assert.equal(generated.json.report_key, report.report_key);
assert.deepEqual(Object.keys(generated.json), csvHeaders);

const gmail = nodesByName.get('Send Report Email');
assert.equal(gmail.parameters.operation, 'send');
assert.equal(gmail.parameters.emailType, 'html');
assert.match(gmail.parameters.sendTo, /recipient_email/);

const buildDelivered = new Function(
  '$json',
  '$',
  nodesByName.get('Build Delivered Row').parameters.jsCode,
);
const delivered = buildDelivered({}, nodeLookup);
assert.equal(delivered.json.delivery_status, 'delivered');
assert.match(delivered.json.delivered_at, /^\d{4}-\d{2}-\d{2}T/);
assert.deepEqual(Object.keys(delivered.json), csvHeaders);

console.log(`Validated ${workflow.nodes.length} nodes and ${csvHeaders.length} Sheet columns.`);
