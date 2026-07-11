package orders2

import "github.com/gin-gonic/gin"

type Store2 struct{}
func (s *Store2) Save() {}
type Service2 struct{ store *Store2 }
func (s *Service2) Create() { s.store.Save() }
type Handler2 struct{ service *Service2 }
func (h *Handler2) Handle() { h.service.Create() }
func Routes2(r *gin.Engine, h *Handler2) { r.GET("/orders/2", h.Handle) }
