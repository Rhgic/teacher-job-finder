const { getFavorites, syncFavoritesFromRemote } = require("../../utils/store")

Page({
  data: {
    favorites: [],
    isEmpty: false
  },
  async onShow() {
    const favorites = getFavorites()
    this.render(favorites)
    this.render(await syncFavoritesFromRemote())
  },
  render(favorites) {
    this.setData({
      favorites,
      isEmpty: favorites.length === 0
    })
  },
  openJob(event) {
    const id = event.currentTarget.dataset.id
    if (id) wx.navigateTo({ url: `/pages/job-detail/index?id=${id}` })
  },
  openCompare() {
    wx.navigateTo({ url: "/pages/job-compare/index" })
  }
})
