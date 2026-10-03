function takePhoto() {
  return new Promise((resolve, reject) => {
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: ['camera'],
      camera: 'back',
      sizeType: ['compressed'],
      success(res) {
        const file = res.tempFiles && res.tempFiles[0]
        if (!file || !file.tempFilePath) {
          reject(new Error('未获取到相机照片'))
          return
        }
        resolve({
          path: file.tempFilePath,
          size: file.size || 0,
          fileType: file.fileType || 'image'
        })
      },
      fail(err) {
        if (err && /cancel/i.test(err.errMsg || '')) {
          reject(new Error('已取消拍照'))
          return
        }
        reject(new Error('无法调用相机，请检查微信相机权限'))
      }
    })
  })
}

module.exports = { takePhoto }
