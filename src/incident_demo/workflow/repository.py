"""Small DynamoDB document repository with optimistic multi-table transactions."""

import json

from incident_demo.workflow.durable import Conflict


class Repository:
    def __init__(self, client, tables):
        self.client, self.tables = client, tables

    def get(self, table, key):
        item = self.client.get_item(
            TableName=self.tables[table], Key={"pk": {"S": key}}, ConsistentRead=True
        ).get("Item")
        return self.decode(item) if item else None

    @staticmethod
    def decode(item):
        return json.loads(item["document"]["S"]) | {"_v": int(item["v"]["N"])}

    def scan(self, table, prefix):
        # Bounded recovery workload; fail rather than silently omit later pages.
        pages = self.client.get_paginator("scan").paginate(
            TableName=self.tables[table],
            FilterExpression="begins_with(pk, :prefix)",
            ExpressionAttributeValues={":prefix": {"S": prefix}},
            ConsistentRead=True,
        )
        count = 0
        for page in pages:
            for item in page["Items"]:
                count += 1
                if count > 200:
                    raise Conflict("recovery scan bound exceeded; operator partitioning required")
                yield item["pk"]["S"], self.decode(item)

    def commit(self, changes):
        operations = []
        for table, key, previous, following in changes:
            base = {
                "TableName": self.tables[table],
                "Key": {"pk": {"S": key}},
                "ConditionExpression": "attribute_not_exists(pk)",
            }
            if previous is not None:
                base |= {
                    "ConditionExpression": "v = :v",
                    "ExpressionAttributeValues": {":v": {"N": str(previous["_v"])}},
                }
            if following is None:
                operations.append({"ConditionCheck": base})
            else:
                version = previous["_v"] + 1 if previous else 1
                document = {k: v for k, v in following.items() if k != "_v"}
                item = base.pop("Key") | {
                    "v": {"N": str(version)},
                    "document": {"S": json.dumps(document, sort_keys=True, separators=(",", ":"))},
                }
                operations.append({"Put": base | {"Item": item}})
        try:
            self.client.transact_write_items(TransactItems=operations)
        except self.client.exceptions.TransactionCanceledException as exc:
            reasons = exc.response.get("CancellationReasons", [])
            if any(r.get("Code") == "ConditionalCheckFailed" for r in reasons):
                raise Conflict("concurrent or duplicate transition") from None
            raise
