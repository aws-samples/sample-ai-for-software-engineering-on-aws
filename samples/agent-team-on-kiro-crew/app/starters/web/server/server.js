// 入口：npm start。端口读环境变量 PORT（默认 3000），只监听 HOST（默认 127.0.0.1）。
import { createApp } from './app.js'

const port = Number(process.env.PORT || 3000)
const host = process.env.HOST || '127.0.0.1'

createApp().listen(port, host, () => {
  console.log(`已启动：http://${host}:${port}`)
})
