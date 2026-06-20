# Wayfair Service Pro — API Documentation

> Extracted from APK `com.wayfair.wayhome` v1.100.0 (versionCode 1960400)

---

## Base URLs

| Environment | URL |
|---|---|
| Production | `https://www.wayfair.com` |
| Secure | `https://secure.wayfair.com` |
| Dev | `https://wayfaircom.csnzoo.com` |

---

## Authentication

### Endpoint

```
POST https://www.wayfair.com/v/wayhome/wayhome_authentication/authenticate
```

### Request Body

```json
{
  "email_address": "user@example.com",
  "password": "...",
  "device_gu_id": "uuid-v4",
  "phone_verification_token": null,
  "lgh": null,
  "context": null,
  "duration": null
}
```

### Headers

| Header | Value |
|---|---|
| `Content-Type` | `application/json` |
| `Accept` | `application/json` |
| `X-PARENT-TXID` | `<uuid>` (transaction tracking) |
| `User-Agent` | `WayfairServicePro/<version> (Android; Build/<code>)` |

### Response

Returns JSON with an auth token used as `Authorization: Bearer <token>`.

### Other Auth Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `v/wayhome/wayhome_authentication/authenticate_with_token` | POST | Re-authenticate with existing token |
| `v/wayhome/wayhome_authentication/logout` | POST | Sign out |
| `v/wayhome/wayhome_authentication/pause_and_logout` | POST | Pause account and logout |

---

## GraphQL API

### Endpoint

```
POST https://www.wayfair.com/wayhome/graphql
```

### Headers

| Header | Value |
|---|---|
| `Authorization` | `Bearer <token>` |
| `x-graph-type` | `3` (wayhome) or `1` (wayfair) |
| `Content-Type` | `application/json` |
| `Accept` | `application/json` |
| `User-Agent` | `WayfairServicePro/<version> ...` |

### Request Format (Apollo Persisted Queries)

The app uses **Apollo Client** with persisted queries. Requests use operation hashes (MD5) instead of full query text:

```json
{
  "operationName": "GetAvailableJobsQueryV2",
  "variables": {
    "startDate": "2025-06-20"
  },
  "extensions": {
    "persistedQuery": {
      "version": 1,
      "sha256Hash": "9552adecb96184eb14097417bfddb695"
    }
  }
}
```

---

## GraphQL Operations

### Queries

| Operation | Hash | Variables |
|---|---|---|
| `GetAvailableJobsQueryV2` | `9552adecb96184eb14097417bfddb695` | `startDate: String!` |
| `GetJobDetailsQueryV2` | `22498828b7bb4e9366eddee089696eb1` | `proJobRoundId: Int!` |
| `GetScheduledJobsQueryV2` | `c67ba4587c04389d9b736952fec2f120` | `fromDate: String!` |
| `JobStatusQueryV2` | `43f50e8ef5a894e697feb58ca39a5c62` | — |
| `GetCancelledCompletedJobsQueryV2` | `37eccd8bcd9668a5ac0487adbad4a05a` | `fromDate: String!` |
| `AssemblyInstructionsQueryV2` | `283c52b4ab14fa8ca1c8abfcfb3c84c0` | `proJobRoundId: Int!` |
| `GetJobPaymentMonthsQuery` | `fb51eeeeac8851932731395a81cbe9da` | — |
| `GetJobPaymentsInvoicedQueryV2` | `bbb0f68699e39e9f5f4a1b105f19a3d4` | `invoicedFrom`, `invoicedTo` |
| `GetQuestionnaireResponsesQueryV2` | `eb1be5a452fd1754c655d2534c6038fc` | `proJobRoundId: Int!` |
| `ProductDetailsQueryV2` | `eac0c5085ff3f5ac50afa6e70b06c98d` | `proJobRoundId: Int!` |
| `SubmitQuestionnaireResponseQueryV2` | `3bf5e2e62de2e9f3d57f54b35e7f6b01` | *complex* |

### Mutations

| Operation | Hash | Variables |
|---|---|---|
| `JobClaimMutationV2` | `351542590863fe8489c5ca20c0095b8f` | `proJobRoundId: Int!`, `date: String!` |
| `JobCancelMutationV2` | `ac99a9bf5c13c6a8448c205becefb42c` | `proJobRoundId: Int!` |
| `JobCheckInWithLocationMutationV2` | `8c564b18dc6ddd1b8b504c6a487b5578` | `proJobRoundId: Int!`, location fields |
| `JobCheckInWithoutLocationMutationV2` | `1df9adeddadb97e019947d57d1e1e30f` | `proJobRoundId: Int!` |
| `JobCheckOutWithLocationMutationV2` | `70d5476c28f82ee8ae919466361d3070` | `proJobRoundId: Int!`, location fields |
| `JobCheckOutWithoutLocationMutationV2` | `94e65b1567fc52f4b9b25481819cd30d` | `proJobRoundId: Int!` |
| `JobUpdateStartTimeMutationV2` | `b2916b8a63260a27699c65f6db2af1f4` | `proJobRoundId: Int!`, `proSelectedDateTime: String!` |
| `JobGeofenceEnterMutation` | `9c998d662551d91d318be1adf04271ac` | `proJobRoundId: Int!` |
| `JobGeofenceExitMutation` | `92499e82271f0438bc41cae3524fbc93` | `proJobRoundId: Int!` |

---

## SSL Pinning

The app uses OkHttp `CertificatePinner` for SSL pinning. This only affects traffic intercepted via a proxy on the mobile device. The bot communicates directly with the server over HTTPS and is **not affected** by SSL pinning.

---

## HTTP Interceptor (HeaderInterceptor)

All HTTP requests go through `HeaderInterceptor.java`:

1. Adds static headers: `Accept: application/json`, `Content-Type: application/json`, `User-Agent: ...`
2. Checks if the request URL matches any registered `authUrls`
3. If matched and `authToken` is set, adds `Authorization: Bearer <token>`

---

## Key Data Models

### AvailableJobsModel

```
proStatus: String
availableJobsMap: Map<String, List<AvailableJobViewModel>>
```

### AvailableJobViewModel

```
proJobRoundId: Int
date: String
... (service details, location, etc.)
```

### JobClaimMutationV2 Input

```
proJobRoundId: Int  — unique job round identifier
date: String        — service date in YYYY-MM-DD format
```
