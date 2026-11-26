# Whitz Admin

运营与运维管理后台（Vue 3 + TypeScript + Vite + Pinia）。

## 功能

总览、用户管理、邀请码、审计日志、运维面板、量化面板、自动化面板。

## 认证

Access Token 仅存内存，Refresh Token 位于 HttpOnly Cookie；非 `admin` 角色刷新会被拒绝并撤销会话。

## 命令

```bash
npm ci
npm run dev
npm run typecheck
npm run build
npm test
```
