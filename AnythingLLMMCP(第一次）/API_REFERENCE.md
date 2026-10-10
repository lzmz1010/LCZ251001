# Pet Hospital REST API 真实接口参考（从运行中的服务抓取）

> 来源：启动 `pethospital.exe` 后调用真实接口抓取。
> 服务地址：`http://127.0.0.1:8080`（运行中，1008 条数据）

## 1. 健康检查 GET /health

```json
{"code":200,"message":"ok","data":{"dbFile":"data/pet.db","petCount":1008,"status":"healthy","timestamp":"2026-09-24T10:58:31+08:00","uptime":"9s"},"time":"2026-09-24T10:58:31+08:00"}
```

## 2. 枚举字典 GET /api/v1/meta（参数允许值权威来源）

- `species`（种类）：`["犬","猫","兔","鸟","仓鼠","爬宠","其他"]`
- `status`（就诊状态）：`["待就诊","就诊中","住院中","已康复","慢性病随访"]`
- `gender`：`["公","母"]`
- `sortFields`（sortBy 允许值）：`["id","name","ownerName","species","doctor","disease","status","totalCost","visitCount","createdAt","updatedAt"]`
- `chargeCategories`：`["检查","药品","手术","住院","疫苗","护理","其他"]`

> `order` 未在 meta 中枚举，README 示例使用 `order=desc`，按惯例允许 `asc`/`desc`。

## 3. 完整字段说明（meta.fields）

`id, name, species, breed, gender, ageMonths, color, chipNo, ownerName, ownerPhone, ownerAddr, doctor, disease, status, allergy, note, records(数组), charges(数组), totalCost(只读汇总), visitCount(只读汇总)`

## 4. GET /api/v1/pets 真实响应结构

查询参数（与 MCP 任务一致）：`q name ownerName ownerPhone species doctor disease status min max sortBy order page pageSize`

响应信封：`{"code":200,"message":"ok","data":{...},"time":"..."}`

`data` 内字段：
```json
{
  "items": [ { 单个宠物对象 } ],
  "total": 1008,          // 总记录数
  "page": 1,              // 当前页
  "pageSize": 1,          // 每页条数
  "totalPages": 1008,     // 总页数
  "totalCost": 3680172.85 // 全部记录总花费汇总
}
```

## 5. 单个宠物对象（含 records/charges 真实表现）

```json
{
  "id": "PET-000682", "name": "汤圆", "species": "犬", "breed": "拉布拉多",
  "gender": "公", "ageMonths": 159, "color": "黑白", "chipNo": "CHIP-280603",
  "ownerName": "郭工程师", "ownerPhone": "18679606421", "ownerAddr": "广州市白云区黄河大道129号",
  "doctor": "王医生", "disease": "蛔虫感染", "status": "已康复", "allergy": "无",
  "records": [ {
    "id": "MR-SEED-000674-00", "visitDate": "2024-08-07", "doctor": "王医生",
    "diagnosis": "蛔虫感染", "symptoms": "消瘦", "treatment": "定期预防",
    "prescription": ["米尔贝肟","芬苯达唑"], "weightKg": 6.45, "temperature": 39.32,
    "followUp": "如症状加重请及时复诊", "charge": 1129.09, "createdAt": "2024-08-07T09:08:00Z"
  } ],
  "charges": [ {
    "id": "CH-SEED-000674-00", "item": "恩诺沙星滴剂", "category": "药品",
    "amount": 101.9, "doctor": "王医生", "date": "2024-08-07"
  } ],
  "totalCost": 1129.09, "visitCount": 1,
  "createdAt": "2026-09-15T13:50:11+08:00", "updatedAt": "2026-09-15T13:50:11+08:00"
}
```

> 说明：样例中 `records`/`charges` 是数组；任务要求兼容 `null` 或数组两种情况（未抓取到 null 实例，需在 MCP 层做 null 容错）。

## 6. GET /api/v1/pets 调用示例

```
curl -s 'http://127.0.0.1:8080/api/v1/pets?species=犬&min=1000&sortBy=totalCost&order=desc&page=1&pageSize=10'
```

## 7. 接口清单

共 29 个接口，详见 `GET /api/v1/endpoints`。MCP 阶段一只需 `GET /api/v1/pets`。
