const { getMaterials, saveMaterialsSynced, syncMaterialsFromRemote } = require("../../utils/store")

const DEFAULT_GROUPS = [
  {
    id: "identity",
    title: "身份与学历",
    items: ["身份证正反面", "本科毕业证", "本科/研究生学位证", "学信网学历验证", "个人近期证件照"]
  },
  {
    id: "teacher",
    title: "教师资质",
    items: ["教师资格证", "普通话证书", "职称或聘任证明", "无犯罪记录承诺材料"]
  },
  {
    id: "application",
    title: "投递材料",
    items: ["个人简历 PDF", "报名登记表", "求职信/自荐信", "岗位要求附件", "作品集或试讲资料"]
  },
  {
    id: "bonus",
    title: "加分证明",
    items: ["获奖证书", "教学成果材料", "班主任/社团经历证明", "论文或课题证明"]
  }
]

function buildDefaultGroups() {
  return DEFAULT_GROUPS.map((group) => ({
    ...group,
    items: group.items.map((name, index) => ({
      id: `${group.id}-${index}`,
      name,
      checked: false
    }))
  }))
}

function flatten(groups) {
  return groups.flatMap((group) => group.items)
}

Page({
  data: {
    groups: [],
    doneCount: 0,
    totalCount: 0,
    percent: 0
  },
  async onShow() {
    const groups = getMaterials() || buildDefaultGroups()
    this.renderGroups(groups)
    const remoteGroups = await syncMaterialsFromRemote(groups)
    this.renderGroups(remoteGroups || groups)
  },
  renderGroups(groups) {
    const items = flatten(groups)
    const doneCount = items.filter((item) => item.checked).length
    const totalCount = items.length
    const percent = totalCount ? Math.round((doneCount / totalCount) * 100) : 0
    this.setData({ groups, doneCount, totalCount, percent })
  },
  async setGroups(groups) {
    this.renderGroups(groups)
    await saveMaterialsSynced(groups)
  },
  toggleItem(event) {
    const { groupId, itemId } = event.currentTarget.dataset
    const groups = this.data.groups.map((group) => {
      if (group.id !== groupId) return group
      return {
        ...group,
        items: group.items.map((item) => (
          item.id === itemId ? { ...item, checked: !item.checked } : item
        ))
      }
    })
    this.setGroups(groups)
  },
  resetList() {
    wx.showModal({
      title: "重置材料清单",
      content: "会把所有勾选状态清空，适合重新准备一轮投递。",
      success: (res) => {
        if (res.confirm) this.setGroups(buildDefaultGroups())
      }
    })
  }
})
