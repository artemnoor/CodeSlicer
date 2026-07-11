package orders7

import "github.com/gin-gonic/gin"

type Store7 struct{}
func (s *Store7) Save() {}
type Service7 struct{ store *Store7 }
func (s *Service7) Create() { s.store.Save() }
type Handler7 struct{ service *Service7 }
func (h *Handler7) Handle() { h.service.Create() }
func Routes7(r *gin.Engine, h *Handler7) { r.GET("/orders/7", h.Handle) }
