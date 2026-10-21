// 页面登记：{ 页面名: { title: 导航上的名字, load: () => import('./<页面名>.js') } }，第一个是首页。
// 前端开发加页面时在这里登记一行（页面名只用小写字母和短横线，和文件名一致）。
export const pages = {
  home: { title: '首页', load: () => import('./home.js') },
}
